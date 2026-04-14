# accounts/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework import generics, filters, status
from rest_framework.pagination import PageNumberPagination
from .permissions import IsManagement, IsSuperAdmin
from leads.models import Lead
from trainers.models import Student
from .models import User, ActivityLog
from rest_framework.exceptions import PermissionDenied
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q

from .serializers import (
    StaffListSerializer,
    StaffDetailSerializer,
    StaffCreateSerializer,
    StaffUpdateSerializer,
    LoginSerializer,
    ActivityLogSerializer
)

# Pagination 
class StaffPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 100


# Dashboard Stats View
class DashboardStatsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != "ADMIN":
            raise PermissionDenied("You are not allowed to view dashboard stats")

        data = {
            "total_leads": Lead.objects.count(),
            "active_staff": User.objects.filter(is_active=True).count(),
            "total_students": Student.objects.count(),
        }
        return Response(data)


# Recent Activities View
class ActivityLogListView(generics.ListAPIView):
    serializer_class   = ActivityLogSerializer
    permission_classes = [IsAuthenticated]
    filter_backends    = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields   = ['action', 'entity_type', 'user']
    search_fields      = ['entity_name', 'description']
    ordering_fields    = ['created_at']
    ordering           = ['-created_at']
 
    def get_queryset(self):
        qs = ActivityLog.objects.select_related('user').all()

        user = self.request.user
        if user.role not in ('ADMIN', 'BUSINESS_HEAD', 'CEO'):
            qs = qs.filter(
                Q(user=user) |
                Q(user__isnull=True, entity_type='Staff', entity_id=user.pk)
            )
        else:
            qs = qs.exclude(
                user__role__in=['ADMIN', 'CEO']
            ).exclude(
                action__in=['USER_LOGIN', 'USER_LOGOUT'] 
            )

        # Date range filters
        date_from = self.request.query_params.get('date_from')
        date_to   = self.request.query_params.get('date_to')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)
 
        return qs


class CurrentUserAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        return Response({
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "phone": user.phone if hasattr(user, 'phone') else None,
            "location": user.location if hasattr(user, 'location') else None,
        })


#Login View 
class LoginAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        refresh = RefreshToken.for_user(user)
        
        # Return refresh token in response body instead of cookie
        return Response({
            "message": "Login successful",
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "role": user.role
            }
        }, status=status.HTTP_200_OK)


# Token Refresh View - Updated
class RefreshTokenAPIView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get("refresh_token")

        if not refresh_token:
            return Response(
                {"detail": "Refresh token not found"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        try:
            refresh = RefreshToken(refresh_token)
            access_token = str(refresh.access_token)

            return Response({
                "access": access_token,
                "refresh": str(refresh) 
            }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"detail": "Invalid or expired refresh token"},
                status=status.HTTP_401_UNAUTHORIZED
            )


#Logout View
class LogoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        response = Response(
            {"message": "Logged out successfully"},
            status=status.HTTP_200_OK
        )
        
        response.delete_cookie(
            key="refresh_token",
            path="/",
            samesite="None",
            secure=True
        )
        
        return response


# Staff List View

class StaffListView(generics.ListAPIView):
    serializer_class = StaffListSerializer
    permission_classes = [IsManagement]
    pagination_class = StaffPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        'username', 'first_name', 'last_name',
        'email', 'role', 'phone', 'location', 'team'
    ]
    ordering_fields = ['date_joined', 'username']
    ordering = ['-date_joined']

    def get_queryset(self):
        queryset = User.objects.filter(is_active=True)

        team = self.request.query_params.get('team')
        if team and team != "all":
            queryset = queryset.filter(team__iexact=team)

        return queryset

# Staff Detail View 
class StaffDetailView(generics.RetrieveAPIView):
    queryset = User.objects.all()
    serializer_class = StaffDetailSerializer
    permission_classes = [IsManagement]


# Staff Create View 
class StaffCreateView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = StaffCreateSerializer
    permission_classes = [IsManagement]

    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        response.data = {"message": "Staff created successfully"}
        return response


# Staff Update View
class StaffUpdateView(generics.UpdateAPIView):
    queryset = User.objects.all()
    serializer_class = StaffUpdateSerializer
    permission_classes = [IsManagement]

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', True)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)

        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        return Response(
            {"message": "Staff updated successfully"},
            status=status.HTTP_200_OK
        )


# Staff Delete View 
class StaffDeleteView(generics.DestroyAPIView):
    queryset = User.objects.all()
    serializer_class = StaffDetailSerializer
    permission_classes = [IsSuperAdmin]

    def destroy(self, request, *args, **kwargs):
        super().destroy(request, *args, **kwargs)
        return Response(
            {"message": "Staff deleted successfully"},
            status=status.HTTP_204_NO_CONTENT
        )




class EmployeeListAPI(APIView):
    def get(self, request):
        employees = User.objects.filter(
            role__in=[
                "ADM_MANAGER",
                "ADM_COUNSELLOR",  
                "ADM_EXEC",
                "FOE",
                "CM"
            ],
            is_active=True
        )

        data = []
        for emp in employees:
            data.append({
                "id": emp.id,
                "name": emp.get_full_name() or emp.username,  
                "role": emp.get_role_display()
            })

        return Response(data)