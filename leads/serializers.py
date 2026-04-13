from rest_framework import serializers
from .models import Lead, ProcessingUpdate, RemarkHistory, LeadAssignment,FollowUp, FollowUpHistory
from accounts.models import User
from django.utils import timezone
from .permissions import FULL_ACCESS_ROLES, MANAGER_ROLES, EXECUTIVE_ROLES


# Shared user serializer
class UserSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model  = User
        fields = ['id', 'username', 'email', 'role', 'first_name', 'last_name']


# Lead Create Serializer
class LeadCreateSerializer(serializers.ModelSerializer):
    assigned_to = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    source      = serializers.CharField(required=False, allow_blank=True, allow_null=True)

    class Meta:
        model  = Lead
        fields = [
            'name', 'phone', 'email', 'source', 'custom_source',
            'priority', 'program', 'location', 'remarks', 'status',
            'assigned_to',
        ]

    def validate_name(self, value):
        value = value.strip()
        if len(value) < 3:
            raise serializers.ValidationError('Name must be at least 3 characters long.')
        return value

    def validate_phone(self, value):
        value = value.strip()
        if not value.isdigit():
            raise serializers.ValidationError('Phone number must contain only digits.')
        if len(value) < 10:
            raise serializers.ValidationError('Phone number must be at least 10 digits.')
        if Lead.objects.filter(phone=value).exists():
            raise serializers.ValidationError('A lead with this phone number already exists.')
        return value

    def validate_assigned_to(self, value):
        if value is None:
            return None

        request = self.context.get('request')
        creator = getattr(request, 'user', None)

        try:
            assignee = User.objects.get(id=value)
        except User.DoesNotExist:
            raise serializers.ValidationError('Assigned user not found.')

        if not assignee.is_active:
            raise serializers.ValidationError('Cannot assign to inactive user.')

        if creator and creator.role == 'ADM_EXEC':
            if assignee != creator:
                raise serializers.ValidationError(
                    'Admission Executives can assign leads only to themselves.'
                )
        elif creator and creator.role == 'FOE':
            if assignee != creator:
                raise serializers.ValidationError(
                    'Front Office Executives can assign leads only to themselves.'
                )
        elif creator and creator.role == 'ADM_MANAGER':
            if assignee != creator and assignee.role not in ['ADM_EXEC', 'FOE']:
                raise serializers.ValidationError(
                    'Admission Managers can assign leads to themselves, FOE, or Admission Executives.'
                )
        elif creator and creator.role in MANAGER_ROLES and creator.role != 'ADM_MANAGER':
            if assignee != creator and assignee.role not in EXECUTIVE_ROLES:
                raise serializers.ValidationError(
                    'Managers can assign leads to themselves or executives only.'
                )
        elif creator and creator.role in FULL_ACCESS_ROLES:
            if assignee.role not in MANAGER_ROLES + EXECUTIVE_ROLES:
                raise serializers.ValidationError(
                    'Admins can assign leads only to managers or executives.'
                )
        else:
            raise serializers.ValidationError('You do not have permission to assign leads.')

        return value

    def validate(self, attrs):
        for field in ['source', 'status', 'priority']:
            if attrs.get(field):
                attrs[field] = attrs[field].upper()

        if attrs.get('source') == 'OTHER' and not attrs.get('custom_source'):
            raise serializers.ValidationError({
                'custom_source': 'This field is required when source is OTHER.'
            })

        if attrs.get('status') in ['REGISTERED', 'COMPLETED']:
            raise serializers.ValidationError({
                'status': 'Cannot create a lead directly with this status.'
            })

        return attrs

    def create(self, validated_data):
        assigned_to_id = validated_data.pop('assigned_to', None)
        request        = self.context.get('request')
        creator        = getattr(request, 'user', None)

        lead = Lead.objects.create(**validated_data)

        if assigned_to_id:
            assignee           = User.objects.get(id=assigned_to_id)
            lead.assigned_to   = assignee
            lead.assigned_by   = creator
            lead.assigned_date = timezone.now()
            lead.save()

            LeadAssignment.objects.create(
                lead=lead,
                assigned_to=assignee,
                assigned_by=creator,
                assignment_type='PRIMARY',
                notes='Initial assignment during lead creation',
            )

        return lead


# Lead Assignment Serializer
class LeadAssignmentSerializer(serializers.ModelSerializer):
    assigned_to = UserSimpleSerializer(read_only=True)
    assigned_by = UserSimpleSerializer(read_only=True)

    class Meta:
        model  = LeadAssignment
        fields = [
            'id', 'lead', 'assigned_to', 'assigned_by',
            'assignment_type', 'notes', 'timestamp',
        ]
        read_only_fields = ['timestamp']


# Lead Assign Serializer (validate + route assign/sub-assign requests)
class LeadAssignSerializer(serializers.Serializer):
    lead_id        = serializers.IntegerField()
    assigned_to_id = serializers.IntegerField()
    notes          = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        user = self.context['request'].user

        try:
            lead = Lead.objects.get(id=attrs['lead_id'])
        except Lead.DoesNotExist:
            raise serializers.ValidationError({'lead_id': 'Lead not found.'})

        try:
            assignee = User.objects.get(id=attrs['assigned_to_id'])
        except User.DoesNotExist:
            raise serializers.ValidationError({'assigned_to_id': 'User not found.'})

        if user.role in FULL_ACCESS_ROLES:
            if assignee.role not in MANAGER_ROLES + EXECUTIVE_ROLES:
                raise serializers.ValidationError({
                    'assigned_to_id': 'Can only assign to managers or executives.'
                })
            attrs['assignment_type'] = 'PRIMARY'

        elif user.role == 'ADM_MANAGER':
            if assignee.role not in ['ADM_EXEC', 'FOE']:
                raise serializers.ValidationError({
                    'assigned_to_id': (
                        'Admission Managers can only assign to '
                        'Front Office Executives or Admission Executives.'
                    )
                })
            if lead.assigned_to != user:
                raise serializers.ValidationError({
                    'lead_id': 'You can only sub-assign leads assigned to you.'
                })
            attrs['assignment_type'] = 'SUB'

        elif user.role in MANAGER_ROLES and user.role != 'ADM_MANAGER':
            if assignee != user and assignee.role not in EXECUTIVE_ROLES:
                raise serializers.ValidationError({
                    'assigned_to_id': 'Managers can only assign to themselves or executives.'
                })
            if lead.assigned_to != user:
                raise serializers.ValidationError({
                    'lead_id': 'You can only sub-assign leads assigned to you.'
                })
            attrs['assignment_type'] = 'SUB'

        elif user.role == 'ADM_EXEC':
            if assignee != user:
                raise serializers.ValidationError({
                    'assigned_to_id': 'Admission Executives can assign leads only to themselves.'
                })
            attrs['assignment_type'] = 'PRIMARY'

        elif user.role == 'FOE':
            if assignee != user:
                raise serializers.ValidationError({
                    'assigned_to_id': 'Front Office Executives can assign leads only to themselves.'
                })
            attrs['assignment_type'] = 'PRIMARY'

        else:
            raise serializers.ValidationError("You don't have permission to assign leads.")

        attrs['lead']     = lead
        attrs['assignee'] = assignee
        return attrs


# Lead List Serializer
class LeadListSerializer(serializers.ModelSerializer):
    assigned_to     = UserSimpleSerializer(read_only=True)
    assigned_by     = UserSimpleSerializer(read_only=True)
    sub_assigned_to = UserSimpleSerializer(read_only=True)
    sub_assigned_by = UserSimpleSerializer(read_only=True)
    current_handler = serializers.SerializerMethodField()

    class Meta:
        model  = Lead
        fields = [
            'id', 'name', 'phone', 'email', 'location',
            'status', 'priority', 'program', 'source', 'custom_source',
            'processing_status',
            'assigned_to', 'assigned_by', 'assigned_date',
            'sub_assigned_to', 'sub_assigned_by', 'sub_assigned_date',
            'current_handler',
            'created_at',
        ]

    def get_current_handler(self, obj):
        handler = obj.current_handler
        if handler is None:
            return None
        return UserSimpleSerializer(handler).data


# Lead Detail Serializer
class LeadDetailSerializer(serializers.ModelSerializer):
    assigned_to          = UserSimpleSerializer(read_only=True)
    assigned_by          = UserSimpleSerializer(read_only=True)
    sub_assigned_to      = UserSimpleSerializer(read_only=True)
    sub_assigned_by      = UserSimpleSerializer(read_only=True)
    processing_executive = UserSimpleSerializer(read_only=True)
    current_handler      = serializers.SerializerMethodField()
    assignment_history   = LeadAssignmentSerializer(many=True, read_only=True)

    class Meta:
        model  = Lead
        fields = '__all__'
        read_only_fields = (
            'created_at', 'updated_at',
            'processing_status_date', 'registration_date',
            'assigned_by', 'assigned_date',
            'sub_assigned_by', 'sub_assigned_date',
        )

    def get_current_handler(self, obj):
        handler = obj.current_handler
        if handler is None:
            return None
        return UserSimpleSerializer(handler).data

    def to_internal_value(self, data):
        data = data.copy() if hasattr(data, 'copy') else dict(data)
        for field in ('priority', 'status', 'source'):
            if data.get(field):
                data[field] = data[field].upper()
        return super().to_internal_value(data)

    def update(self, instance, validated_data):
        request = self.context.get('request')

        if 'remarks' in validated_data and instance.remarks != validated_data.get('remarks'):
            RemarkHistory.objects.create(
                lead=instance,
                previous_remarks=instance.remarks,
                new_remarks=validated_data.get('remarks'),
                changed_by=request.user if request else None,
            )

        new_status = validated_data.get('status')
        if new_status is not None and not new_status.strip():
            raise serializers.ValidationError({'status': 'Status cannot be empty.'})

        return super().update(instance, validated_data)


# Processing Update Serializer
class ProcessingUpdateSerializer(serializers.ModelSerializer):
    changed_by = UserSimpleSerializer(read_only=True)

    class Meta:
        model  = ProcessingUpdate
        fields = ['id', 'lead', 'status', 'changed_by', 'notes', 'timestamp']
        read_only_fields = ('timestamp', 'changed_by')

    def validate_status(self, value):
        if value not in dict(Lead.PROCESSING_STATUS_CHOICES).keys():
            raise serializers.ValidationError('Invalid processing status.')
        return value


# Remark History Serializer
class RemarkHistorySerializer(serializers.ModelSerializer):
    changed_by = UserSimpleSerializer(read_only=True)

    class Meta:
        model  = RemarkHistory
        fields = [
            'id', 'lead', 'previous_remarks', 'new_remarks',
            'changed_by', 'changed_at',
        ]
        read_only_fields = ('changed_at',)

    def validate_changed_by(self, value):
        if not value:
            raise serializers.ValidationError('Changed by must be provided.')
        return value


# Lead Update Serializer (PATCH – used by UpdateLeadView)
class LeadUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Lead
        fields = [
            'name', 'phone', 'email', 'location', 'remarks',
            'priority', 'status', 'program', 'source', 'custom_source',
        ]

    def validate_priority(self, value):
        if value not in dict(Lead.PRIORITY_CHOICES):
            raise serializers.ValidationError('Invalid priority')
        return value.upper()

    def validate_status(self, value):
        if not value:
            raise serializers.ValidationError('Status cannot be empty')
        return value.upper()

    def update(self, instance, validated_data):
        request = self.context['request']

        if 'remarks' in validated_data and instance.remarks != validated_data['remarks']:
            RemarkHistory.objects.create(
                lead=instance,
                previous_remarks=instance.remarks,
                new_remarks=validated_data['remarks'],
                changed_by=request.user,
            )

        return super().update(instance, validated_data)


# Bulk Lead Create Serializer
class BulkLeadCreateSerializer(LeadCreateSerializer):
    assigned_to = serializers.CharField(required=True)

    def validate_assigned_to(self, value):
        user_map = self.context.get('user_map', {})
        user = user_map.get(value.lower())

        if not user:
            raise serializers.ValidationError(f"User '{value}' not found.")

        if not user.is_active:
            raise serializers.ValidationError(f"User '{value}' is inactive.")

        # Leads can only be assigned to managers or executives, never to admin/CEO/OPS etc.
        if user.role not in MANAGER_ROLES + EXECUTIVE_ROLES:
            raise serializers.ValidationError(
                f"Cannot assign leads to '{value}' (role '{user.role}'). "
                f"Only managers and executives can be assigned leads."
            )

        return user
    
    def validate_phone(self, value):
        if value is None:
            return value  # let the required-field check handle this if phone is required
        digits_only = ''.join(filter(str.isdigit, str(value)))
        if len(digits_only) > 10:
            raise serializers.ValidationError(
                f"Phone number must not exceed 10 digits (got {len(digits_only)})."
            )
        return value

    def validate(self, attrs):
        # Skip the status restriction from LeadCreateSerializer for bulk uploads:
        # 'assigned_to' is already a User object here (resolved in validate_assigned_to),
        # so we only run the field-level uppercase normalisation and source checks.
        for field in ['source', 'status', 'priority']:
            if attrs.get(field):
                attrs[field] = attrs[field].upper()

        if attrs.get('source') == 'OTHER' and not attrs.get('custom_source'):
            raise serializers.ValidationError({
                'custom_source': 'This field is required when source is OTHER.'
            })

        if attrs.get('status') in ['REGISTERED', 'COMPLETED']:
            raise serializers.ValidationError({
                'status': 'Cannot create a lead directly with this status.'
            })

        return attrs

    def create(self, validated_data):
        assignee = validated_data.pop('assigned_to')  
        request  = self.context.get('request')
        creator  = getattr(request, 'user', None)

        lead = Lead.objects.create(**validated_data)

        lead.assigned_to   = assignee
        lead.assigned_by   = creator
        lead.assigned_date = timezone.now()
        lead.save()

        LeadAssignment.objects.create(
            lead=lead,
            assigned_to=assignee,
            assigned_by=creator,
            assignment_type='PRIMARY',
            notes='Assigned during bulk upload',
        )

        return lead



class FollowUpSerializer(serializers.ModelSerializer):
    is_overdue      = serializers.ReadOnlyField()
    contact_display = serializers.ReadOnlyField()
    assigned_to     = UserSimpleSerializer(read_only=True)  # ← nested, not just ID
    assigned_to_id  = serializers.PrimaryKeyRelatedField(   # ← for writes
        queryset=User.objects.all(),
        source='assigned_to',
        write_only=True,
        required=False
    )

    class Meta:
        model  = FollowUp
        fields = '__all__'
        read_only_fields = [
            'assigned_to',
            'converted_at',
            'reminder_sent_at',
            'created_at',
            'updated_at',
        ]

        

class FollowUpHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = FollowUpHistory
        fields = '__all__'