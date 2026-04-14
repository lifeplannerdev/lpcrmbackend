import pandas as pd
import math
from datetime import date
from .models import Lead, ProcessingUpdate, RemarkHistory, LeadAssignment,FollowUp,LeadConversionDetail
from .email_utils import send_conversion_email
from rest_framework import generics, filters, status
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.models import User
from django.shortcuts import get_object_or_404
from django.db import models, transaction
from django.db.models import Count, Q as DQ
from django.utils import timezone
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from accounts.models import ActivityLog  
from utils.pusher import pusher_client, trigger_pusher
from utils import notify_lead_assigned
from rest_framework import status
from django.shortcuts import get_object_or_404


from leads.permissions import (
    CanAccessLeads,
    CanAssignLeads,
    CanViewAllLeads,
    CanModifyAllLeads,
    FULL_ACCESS_ROLES,
    MANAGER_ROLES,
    EXECUTIVE_ROLES,
    CanManageConversion,
)

from .serializers import (
    LeadListSerializer,
    LeadDetailSerializer,
    LeadCreateSerializer,
    ProcessingUpdateSerializer,
    LeadAssignSerializer,
    LeadAssignmentSerializer,
    LeadUpdateSerializer,
    BulkLeadCreateSerializer,
    FollowUpSerializer,
    LeadConversionDetailSerializer,
)


# ── Helpers
def clean_value(val):
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    return val


# ── Pagination
class LeadPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ── Lead List View
class LeadListView(generics.ListAPIView):
    serializer_class = LeadListSerializer
    permission_classes = [CanAccessLeads]
    pagination_class = LeadPagination

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = {
        'priority':          ['exact'],
        'status':            ['exact', 'iexact'],
        'source':            ['exact'],
        'processing_status': ['exact'],
        'assigned_to':       ['exact', 'isnull'],
        'sub_assigned_to':   ['exact'],
    }
    search_fields   = ['name', 'phone', 'email', 'program']
    ordering_fields = ['created_at', 'priority']
    ordering        = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        base_qs = Lead.objects.select_related(
            'assigned_to', 'assigned_by',
            'sub_assigned_to', 'sub_assigned_by',
        )
        if user.role in FULL_ACCESS_ROLES:
            return base_qs.all().distinct()
        return base_qs.filter(
            models.Q(assigned_to=user) |
            models.Q(sub_assigned_to=user)
        ).distinct()

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
        else:
            serializer = self.get_serializer(queryset, many=True)

        stats = queryset.aggregate(
            new=Count('id', filter=DQ(status__iexact='ENQUIRY')),
            qualified=Count('id', filter=DQ(status__iexact='QUALIFIED')),
            converted=Count('id', filter=DQ(status__iexact='CONVERTED')),
            total_assigned=Count('id', filter=DQ(assigned_to=request.user)),
            total_sub_assigned=Count('id', filter=DQ(sub_assigned_to=request.user)),
        )

        return self.get_paginated_response({
            'leads': serializer.data,
            'stats': stats,
        })


# ── Lead Create View
class LeadCreateView(generics.CreateAPIView):
    queryset = Lead.objects.all()
    serializer_class = LeadCreateSerializer
    permission_classes = [CanAccessLeads]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        lead = serializer.save(created_by=request.user)

        ActivityLog.objects.create(
            user=request.user,
            action='LEAD_CREATED',
            entity_type='Lead',
            entity_id=lead.id,
            entity_name=lead.name,
            description=f'Lead "{lead.name}" was created by {request.user.get_full_name() or request.user.username}',
            metadata={'phone': lead.phone, 'source': lead.source}
        )

        if getattr(lead, 'processing_status', None) and lead.processing_status != 'PENDING':
            ProcessingUpdate.objects.create(
                lead=lead,
                status=lead.processing_status,
                changed_by=request.user,
                notes='Initial status on lead creation'
            )

        if lead.assigned_to and lead.assigned_to != request.user:
            notify_lead_assigned(
                assignee=lead.assigned_to,
                assigned_by=request.user,
                lead=lead,
                assignment_type='PRIMARY',
            )

        return Response({
            'message': 'Lead created successfully',
            'lead_id': lead.id
        }, status=status.HTTP_201_CREATED)


class LeadDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = LeadDetailSerializer
    permission_classes = [CanAccessLeads]

    def get_queryset(self):
        user = self.request.user
        base_qs = Lead.objects.select_related(
            'assigned_to', 'assigned_by',
            'sub_assigned_to', 'sub_assigned_by',
        )
        if user.role in FULL_ACCESS_ROLES:
            return base_qs.all()
        return base_qs.filter(
            models.Q(assigned_to=user) |
            models.Q(sub_assigned_to=user)
        )

    def update(self, request, *args, **kwargs):
        partial  = kwargs.pop('partial', False)
        lead     = self.get_object()
        old_processing_status = lead.processing_status
        old_status            = lead.status

        serializer = self.get_serializer(lead, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        updated_lead = serializer.save()

        if old_processing_status != updated_lead.processing_status:
            ProcessingUpdate.objects.create(
                lead=updated_lead,
                status=updated_lead.processing_status,
                changed_by=request.user,
                notes='Status updated via API'
            )

        if old_status != updated_lead.status:
            ActivityLog.objects.create(
                user=request.user,
                action='LEAD_STATUS_CHANGED',
                entity_type='Lead',
                entity_id=updated_lead.id,
                entity_name=updated_lead.name,
                description=f'Lead "{updated_lead.name}" status changed from {old_status} → {updated_lead.status}',
                metadata={
                    'old_status': old_status,
                    'new_status': updated_lead.status,
                }
            )

        if old_status != 'CONVERTED' and updated_lead.status == 'CONVERTED':
            send_conversion_email(updated_lead)

        return Response({
            'message': 'Lead updated successfully',
            'lead': LeadDetailSerializer(updated_lead).data,
        }, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        lead = self.get_object()
        user = request.user

        if (
            user.role not in FULL_ACCESS_ROLES and
            lead.assigned_to != user and
            lead.sub_assigned_to != user
        ):
            return Response(
                {'error': 'You do not have permission to delete this lead'},
                status=status.HTTP_403_FORBIDDEN,
            )

        ActivityLog.objects.create(
            user=request.user,
            action='LEAD_DELETED',
            entity_type='Lead',
            entity_id=lead.id,
            entity_name=lead.name,
            description=f'Lead "{lead.name}" was deleted by {request.user.get_full_name() or request.user.username}',
            metadata={
                'phone':       lead.phone,
                'status':      lead.status,
                'assigned_to': lead.assigned_to.get_full_name() if lead.assigned_to else None,
            }
        )

        self.perform_destroy(lead)
        return Response(
            {'message': 'Lead deleted successfully'},
            status=status.HTTP_204_NO_CONTENT,
        )

# ── Lead Processing Timeline View
class LeadProcessingTimelineView(generics.ListAPIView):
    serializer_class = ProcessingUpdateSerializer
    permission_classes = [CanAccessLeads]

    def get_queryset(self):
        lead_id = self.kwargs.get('lead_id')
        lead    = get_object_or_404(Lead, id=lead_id)
        user    = self.request.user

        if user.role in FULL_ACCESS_ROLES:
            return ProcessingUpdate.objects.filter(lead=lead).order_by('-timestamp')

        if lead.assigned_to != user and lead.sub_assigned_to != user:
            return ProcessingUpdate.objects.none()

        return ProcessingUpdate.objects.filter(lead=lead).order_by('-timestamp')


# ── Lead Assignment View
class LeadAssignView(APIView):
    permission_classes = [CanAssignLeads]

    def post(self, request):
        serializer = LeadAssignSerializer(
            data=request.data, context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        lead            = serializer.validated_data['lead']
        assignee        = serializer.validated_data['assignee']
        assignment_type = serializer.validated_data['assignment_type']
        notes           = serializer.validated_data.get('notes', '')

        if assignment_type == 'PRIMARY':
            lead.assigned_to       = assignee
            lead.assigned_by       = request.user
            lead.assigned_date     = timezone.now()
            lead.sub_assigned_to   = None
            lead.sub_assigned_by   = None
            lead.sub_assigned_date = None

        elif assignment_type == 'SUB':
            lead.sub_assigned_to   = assignee
            lead.sub_assigned_by   = request.user
            lead.sub_assigned_date = timezone.now()

        lead.save()

        LeadAssignment.objects.create(
            lead=lead,
            assigned_to=assignee,
            assigned_by=request.user,
            assignment_type=assignment_type,
            notes=notes,
        )

        if assignee != request.user:
            notify_lead_assigned(
                assignee=assignee,
                assigned_by=request.user,
                lead=lead,
                assignment_type=assignment_type,
            )

        return Response({
            'message': 'Lead assigned successfully',
            'lead': LeadDetailSerializer(lead).data,
        }, status=status.HTTP_200_OK)


# ── Bulk Lead Assignment View
class BulkLeadAssignView(APIView):
    permission_classes = [CanAssignLeads]

    def post(self, request):
        lead_ids       = request.data.get('lead_ids', [])
        assigned_to_id = request.data.get('assigned_to_id')
        notes          = request.data.get('notes', '')

        if not lead_ids or not isinstance(lead_ids, list):
            return Response(
                {'error': 'lead_ids must be a non-empty list'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not assigned_to_id:
            return Response(
                {'error': 'assigned_to_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user          = request.user
        success_count = 0
        failed_leads  = []
        assigned_summary = {}

        for lead_id in lead_ids:
            try:
                serializer = LeadAssignSerializer(
                    data={
                        'lead_id':        lead_id,
                        'assigned_to_id': assigned_to_id,
                        'notes':          notes,
                    },
                    context={'request': request},
                )

                if serializer.is_valid():
                    lead            = serializer.validated_data['lead']
                    assignee        = serializer.validated_data['assignee']
                    assignment_type = serializer.validated_data['assignment_type']

                    if assignment_type == 'PRIMARY':
                        lead.assigned_to       = assignee
                        lead.assigned_by       = user
                        lead.assigned_date     = timezone.now()
                        lead.sub_assigned_to   = None
                        lead.sub_assigned_by   = None
                        lead.sub_assigned_date = None
                    elif assignment_type == 'SUB':
                        lead.sub_assigned_to   = assignee
                        lead.sub_assigned_by   = user
                        lead.sub_assigned_date = timezone.now()

                    lead.save()

                    LeadAssignment.objects.create(
                        lead=lead,
                        assigned_to=assignee,
                        assigned_by=user,
                        assignment_type=assignment_type,
                        notes=notes,
                    )
                    success_count += 1

                    if assignee == user:
                        continue

                    uid = assignee.id
                    if uid not in assigned_summary:
                        assigned_summary[uid] = {
                            'user':  assignee,
                            'leads': [],
                            'type':  assignment_type,
                        }
                    assigned_summary[uid]['leads'].append({
                        'lead_id':   lead.id,
                        'lead_name': lead.name,
                        'priority':  lead.priority,
                    })

                else:
                    failed_leads.append({'lead_id': lead_id, 'errors': serializer.errors})

            except Exception as e:
                failed_leads.append({'lead_id': lead_id, 'error': str(e)})

        # 🔔 One grouped Pusher notification per assignee (self-assignments already excluded above)
        for uid, summary in assigned_summary.items():
            count = len(summary['leads'])
            trigger_pusher(
                channel=f'private-user-{uid}',
                event='lead.assigned',
                data={
                    'bulk':             True,
                    'count':            count,
                    'leads':            summary['leads'],
                    'assignment_type':  summary['type'],
                    'assigned_by_id':   user.id,
                    'assigned_by_name': user.get_full_name() or user.username,
                    'message': (
                        f"{count} lead{'s' if count > 1 else ''} assigned to you "
                        f"by {user.get_full_name() or user.username}"
                    ),
                }
            )

        return Response({
            'message':       f'Successfully assigned {success_count} leads',
            'success_count': success_count,
            'failed_count':  len(failed_leads),
            'failed_leads':  failed_leads,
        }, status=status.HTTP_200_OK)


# ── Lead Assignment History View
class LeadAssignmentHistoryView(generics.ListAPIView):
    serializer_class   = LeadAssignmentSerializer
    permission_classes = [CanAccessLeads]

    def get_queryset(self):
        lead_id = self.kwargs.get('lead_id')
        lead    = get_object_or_404(Lead, id=lead_id)
        user    = self.request.user

        if user.role in FULL_ACCESS_ROLES:
            return LeadAssignment.objects.filter(lead=lead).order_by('-timestamp')

        if lead.assigned_to != user and lead.sub_assigned_to != user:
            return LeadAssignment.objects.none()

        return LeadAssignment.objects.filter(lead=lead).order_by('-timestamp')


# ── My Team Leads View
class MyTeamLeadsView(generics.ListAPIView):
    serializer_class   = LeadListSerializer
    permission_classes = [CanAccessLeads]
    pagination_class   = LeadPagination

    def get_queryset(self):
        user = self.request.user
        base_qs = Lead.objects.select_related(
            'assigned_to', 'assigned_by',
            'sub_assigned_to', 'sub_assigned_by',
        )
        if user.role in FULL_ACCESS_ROLES:
            return base_qs.all().distinct()
        return base_qs.filter(
            models.Q(assigned_to=user) |
            models.Q(sub_assigned_to=user)
        ).distinct()


# ── Available Users for Assignment
class AvailableUsersForAssignmentView(APIView):
    permission_classes = [CanAssignLeads]

    def get(self, request):
        ASSIGNABLE_ROLES = [
            'OPS', 'ADM_MANAGER', 'ADM_EXEC',
            'CM', 'BDM', 'FOE', 'ADM_COUNSELLOR',
        ]
        users = User.objects.filter(
            role__in=ASSIGNABLE_ROLES,
            is_active=True,
        ).values(
            'id', 'username', 'email', 'role', 'first_name', 'last_name'
        ).order_by('role', 'first_name', 'last_name')

        return Response(list(users), status=status.HTTP_200_OK)


# ── Unassign Lead View
class UnassignLeadView(APIView):
    permission_classes = [CanAssignLeads]

    def post(self, request):
        lead_id       = request.data.get('lead_id')
        unassign_type = request.data.get('unassign_type', 'SUB')

        if not lead_id:
            return Response(
                {'error': 'lead_id is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            lead = Lead.objects.get(id=lead_id)
        except Lead.DoesNotExist:
            return Response(
                {'error': 'Lead not found'},
                status=status.HTTP_404_NOT_FOUND,
            )

        user = request.user

        if user.role == 'ADM_EXEC':
            return Response(
                {'error': 'Admission Executives cannot unassign leads'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if user.role in FULL_ACCESS_ROLES:
            if unassign_type == 'PRIMARY':
                lead.assigned_to       = None
                lead.assigned_by       = None
                lead.assigned_date     = None
                lead.sub_assigned_to   = None
                lead.sub_assigned_by   = None
                lead.sub_assigned_date = None
            elif unassign_type == 'SUB':
                lead.sub_assigned_to   = None
                lead.sub_assigned_by   = None
                lead.sub_assigned_date = None

        elif user.role == 'ADM_MANAGER':
            if lead.assigned_to != user:
                return Response(
                    {'error': 'You can only unassign leads assigned to you'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            lead.sub_assigned_to   = None
            lead.sub_assigned_by   = None
            lead.sub_assigned_date = None

        else:
            return Response(
                {'error': 'You do not have permission to unassign leads'},
                status=status.HTTP_403_FORBIDDEN,
            )

        lead.save()

        return Response({
            'message': 'Lead unassigned successfully',
            'lead':    LeadDetailSerializer(lead).data,
        }, status=status.HTTP_200_OK)


# ── Update Lead View
class UpdateLeadView(APIView):
    permission_classes = [CanAccessLeads]

    def patch(self, request, pk):
        lead = get_object_or_404(Lead, id=pk)

        if (
            lead.assigned_to != request.user
            and lead.sub_assigned_to != request.user
            and request.user.role not in FULL_ACCESS_ROLES
        ):
            return Response(
                {'error': 'Permission denied'},
                status=status.HTTP_403_FORBIDDEN,
            )

        old_status = lead.status

        serializer = LeadUpdateSerializer(
            lead,
            data=request.data,
            partial=True,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        updated_lead = serializer.save()

        if old_status != 'CONVERTED' and updated_lead.status == 'CONVERTED':
            send_conversion_email(updated_lead)

        return Response(serializer.data, status=status.HTTP_200_OK)


# ── Bulk Lead Upload View
class BulkLeadUploadView(APIView):
    permission_classes = [CanAccessLeads]
    parser_classes     = [MultiPartParser, FormParser]

    def post(self, request):
        file = request.FILES.get('file')

        if not file:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        if file.size > 5 * 1024 * 1024:
            return Response({'error': 'File too large (max 5MB)'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            df = pd.read_excel(file)
        except Exception:
            return Response({'error': 'Invalid Excel file'}, status=status.HTTP_400_BAD_REQUEST)

        required_columns = ['name', 'phone', 'assigned_to']
        missing_cols = [col for col in required_columns if col not in df.columns]

        if missing_cols:
            return Response(
                {'error': f'Missing required columns: {missing_cols}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_map = {
            user.username.lower(): user
            for user in User.objects.filter(is_active=True)
        }

        success_count    = 0
        failed_rows      = []
        assigned_summary = {}
        seen_phones      = set()  #  tracks phones already processed in this batch

        for index, row in df.iterrows():
            try:
                name       = clean_value(row.get('name'))
                email      = clean_value(row.get('email'))
                source     = clean_value(row.get('source'))
                status_val = clean_value(row.get('status'))
                priority   = clean_value(row.get('priority'))
                program    = clean_value(row.get('program'))
                location   = clean_value(row.get('location'))
                raw_username = clean_value(row.get('assigned_to'))
                username = str(raw_username).strip() if raw_username is not None else None

                # Preserve leading zeros: treat phone as string from the start
                phone = clean_value(row.get('phone'))
                if phone is not None:
                    # Excel stores numbers as floats; strip the decimal and keep as string
                    phone = str(int(float(str(phone)))) if str(phone).replace('.', '', 1).isdigit() else str(phone).strip()

                #  Within-batch duplicate check (before any DB or serializer work)
                if phone and phone in seen_phones:
                    failed_rows.append({
                        'row':   index + 2,
                        'error': f"Duplicate phone '{phone}' already exists in this file.",
                    })
                    continue

                #  DB duplicate check
                if phone and Lead.objects.filter(phone=phone).exists():
                    failed_rows.append({
                        'row':   index + 2,
                        'error': f"Phone '{phone}' already exists in the system.",
                    })
                    continue

                # Phone passed both duplicate checks — reserve it for this batch
                if phone:
                    seen_phones.add(phone)

                if not username:
                    failed_rows.append({'row': index + 2, 'error': 'assigned_to is required'})
                    continue

                assignee_user = user_map.get(str(username).lower())
                if not assignee_user:
                    failed_rows.append({
                        'row':   index + 2,
                        'error': f"User '{username}' not found",
                    })
                    continue

                data = {
                    'name':        name,
                    'phone':       phone,
                    'email':       email,
                    'status':      str(status_val).upper() if status_val else 'ENQUIRY',
                    'priority':    str(priority).upper()   if priority   else 'MEDIUM',
                    'program':     program,
                    'location':    location,
                    'assigned_to': str(username),
                }
                if source:
                    data['source'] = str(source).upper()

                serializer = BulkLeadCreateSerializer(
                    data=data,
                    context={'request': request, 'user_map': user_map},
                )

                if serializer.is_valid():
                    # Each row saved in its own savepoint — a failure here won't roll back prior successes
                    try:
                        with transaction.atomic():
                            lead = serializer.save()
                    except Exception as db_err:
                        failed_rows.append({'row': index + 2, 'error': str(db_err)})
                        continue

                    success_count += 1

                    # Skip notification summary if uploader assigned to themselves
                    if assignee_user == request.user:
                        continue

                    uid = assignee_user.id
                    if uid not in assigned_summary:
                        assigned_summary[uid] = {
                            'user':  assignee_user,
                            'leads': [],
                        }
                    assigned_summary[uid]['leads'].append({
                        'lead_id':   lead.id,
                        'lead_name': lead.name,
                        'priority':  lead.priority,
                    })

                else:
                    failed_rows.append({
                        'row':    index + 2,
                        'data':   data,
                        'errors': serializer.errors,
                    })

            except Exception as e:
                failed_rows.append({'row': index + 2, 'error': str(e)})

        # 🔔 One grouped Pusher notification per assignee (self-assignments already excluded above)
        for uid, summary in assigned_summary.items():
            count = len(summary['leads'])
            trigger_pusher(
                channel=f'private-user-{uid}',
                event='lead.assigned',
                data={
                    'bulk':             True,
                    'count':            count,
                    'leads':            summary['leads'],
                    'assignment_type':  'PRIMARY',
                    'assigned_by_id':   request.user.id,
                    'assigned_by_name': request.user.get_full_name() or request.user.username,
                    'message': (
                        f"{count} new lead{'s' if count > 1 else ''} uploaded and "
                        f"assigned to you by {request.user.get_full_name() or request.user.username}"
                    ),
                }
            )

        return Response({
            'message':       'Bulk upload completed',
            'success_count': success_count,
            'failed_count':  len(failed_rows),
            'failed_rows':   failed_rows,
        }, status=status.HTTP_200_OK)


# ── Today's Leads
class TodayLeadsAPI(APIView):
    permission_classes = [CanAccessLeads]

    def get(self, request):
        today = date.today()
        leads = Lead.objects.filter(
            created_at__date=today
        ).values('id', 'name', 'status', 'assigned_to')
        return Response(list(leads))



class FollowUpListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # ADMIN/CEO/OPS see all follow-ups; others see only their own
        if user.role in FULL_ACCESS_ROLES:
            queryset = FollowUp.objects.all()
        else:
            queryset = FollowUp.objects.filter(assigned_to=user)

        # rest of your filters stay exactly the same ...
        lead_id       = request.query_params.get('lead')
        date          = request.query_params.get('date')
        start_date    = request.query_params.get('start_date')
        end_date      = request.query_params.get('end_date')
        status        = request.query_params.get('status')
        overdue       = request.query_params.get('overdue')
        followup_type = request.query_params.get('followup_type')
        priority      = request.query_params.get('priority')
        search        = request.query_params.get('search')

        if lead_id:
            queryset = queryset.filter(lead_id=lead_id)
        if date:
            queryset = queryset.filter(follow_up_date=date)
        if start_date and end_date:
            queryset = queryset.filter(follow_up_date__range=[start_date, end_date])
        if status:
            queryset = queryset.filter(status=status)
        if overdue == 'true':
            queryset = queryset.filter(
                follow_up_date__lt=timezone.now().date(),
                status='pending'
            )
        if followup_type:
            queryset = queryset.filter(followup_type=followup_type)
        if priority:
            queryset = queryset.filter(priority=priority)
        if search:
            queryset = queryset.filter(
                models.Q(name__icontains=search) |
                models.Q(phone_number__icontains=search)
            )

        queryset = queryset.order_by('follow_up_date', 'follow_up_time')
        serializer = FollowUpSerializer(queryset, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = FollowUpSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(assigned_to=request.user)
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


class FollowUpDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, pk, user):
        if user.role in FULL_ACCESS_ROLES:
            return get_object_or_404(FollowUp, pk=pk)
        return get_object_or_404(FollowUp, pk=pk, assigned_to=user)

    def get(self, request, pk):
        followup = self.get_object(pk, request.user)
        serializer = FollowUpSerializer(followup)
        return Response(serializer.data)

    def put(self, request, pk):
        followup = self.get_object(pk, request.user)
        serializer = FollowUpSerializer(followup, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)

        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        followup = self.get_object(pk, request.user)
        followup.delete()
        return Response({"message": "Deleted successfully"}, status=204)



class TodayFollowUpsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.now().date()

        # Admin sees all today's follow-ups
        if request.user.role in FULL_ACCESS_ROLES:
            queryset = FollowUp.objects.filter(follow_up_date=today)
        else:
            queryset = FollowUp.objects.filter(
                assigned_to=request.user,
                follow_up_date=today
            )

        serializer = FollowUpSerializer(queryset, many=True)
        return Response(serializer.data)


class OverdueFollowUpsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        today = timezone.now().date()

        # Admin sees all overdue follow-ups
        if request.user.role in FULL_ACCESS_ROLES:
            queryset = FollowUp.objects.filter(
                follow_up_date__lt=today,
                status='pending'
            )
        else:
            queryset = FollowUp.objects.filter(
                assigned_to=request.user,
                follow_up_date__lt=today,
                status='pending'
            )

        serializer = FollowUpSerializer(queryset, many=True)
        return Response(serializer.data)


class LeadConversionDetailView(APIView):
    
    def get_permissions(self):
        if self.request.method == 'GET':
            return [CanAccessLeads()]
        return [CanManageConversion()]

    def get(self, request, lead_id):
        lead = get_object_or_404(Lead, id=lead_id)

        if lead.status != 'CONVERTED':
            return Response(
                {'error': 'This lead is not converted yet.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            detail     = lead.conversion_detail
            serializer = LeadConversionDetailSerializer(detail)
            return Response(serializer.data)
        except LeadConversionDetail.DoesNotExist:
            return Response(
                {'detail': None, 'message': 'No conversion details filled yet.'},
                status=status.HTTP_204_NO_CONTENT
            )

    def post(self, request, lead_id):
        lead = get_object_or_404(Lead, id=lead_id)

        if lead.status != 'CONVERTED':
            return Response(
                {'error': 'Can only add conversion details to a CONVERTED lead.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if hasattr(lead, 'conversion_detail'):
            return Response(
                {'error': 'Conversion detail already exists. Use PATCH to update.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = LeadConversionDetailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        detail = serializer.save(lead=lead, updated_by=request.user)

        ActivityLog.objects.create(
            user=request.user,
            action='LEAD_UPDATED',
            entity_type='Lead',
            entity_id=lead.id,
            entity_name=lead.name,
            description=f'Conversion details added for "{lead.name}" by {request.user.get_full_name() or request.user.username}',
            metadata={
                'student_name': detail.student_name,
                'course':       detail.course,
                'payment_status': detail.payment_status,
            }
        )

        return Response(
            LeadConversionDetailSerializer(detail).data,
            status=status.HTTP_201_CREATED
        )

    def patch(self, request, lead_id):
        lead   = get_object_or_404(Lead, id=lead_id)
        detail = get_object_or_404(LeadConversionDetail, lead=lead)

        serializer = LeadConversionDetailSerializer(
            detail, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        updated = serializer.save(updated_by=request.user)

        ActivityLog.objects.create(
            user=request.user,
            action='LEAD_UPDATED',
            entity_type='Lead',
            entity_id=lead.id,
            entity_name=lead.name,
            description=f'Conversion details updated for "{lead.name}" by {request.user.get_full_name() or request.user.username}',
            metadata={'payment_status': updated.payment_status}
        )

        return Response(LeadConversionDetailSerializer(updated).data)