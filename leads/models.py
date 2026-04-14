from django.db import models
from accounts.models import User
from django.utils import timezone
from django.core.validators import MinLengthValidator
from django.contrib.auth import get_user_model

User = get_user_model()

class Lead(models.Model):
    PRIORITY_CHOICES = [
        ('HIGH', 'High'),
        ('MEDIUM', 'Medium'), 
        ('LOW', 'Low')
    ]
    
    SOURCE_CHOICES = [
        ('WHATSAPP', 'WhatsApp'),
        ('INSTAGRAM', 'Instagram'),
        ('WEBSITE', 'Website'),
        ('WALK_IN', 'Walk-in'),
        ('AUTOMATION', 'Automation'),
        ('OTHER', 'Other'),
        ('ADS','Ads'),
        ('VOXBAY CALL','Voxbay'),
        ('BULK DATA','Bulk data')
    ]
        
    PROCESSING_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('FORWARDED', 'Forwarded to Processing'),
        ('ACCEPTED', 'Accepted by Processing'),
        ('PROCESSING', 'In Processing'),
        ('COMPLETED', 'Processing Completed'),
        ('REJECTED', 'Processing Rejected')
    ]

    DOCUMENT_STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('COLLECTED', 'Collected'),
        ('VERIFIED', 'Verified'),
        ('SUBMITTED', 'Submitted'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected')
    ]
    STATUS_CHOICES = [
    ('ENQUIRY', 'Enquiry'),
    ('QUALIFIED', 'Qualified'),
    ('NOT_INTERESTED', 'Not Interested'),
    ('CONVERTED', 'Converted'),
    ('CNR', 'Could Not Reach'),
    ('REGISTERED', 'Registered'),
]
    # Basic lead info
    name = models.CharField(max_length=100, validators=[MinLengthValidator(3)])
    phone = models.CharField(max_length=20, validators=[MinLengthValidator(10)], unique=True, help_text="Contact phone number")
    email = models.EmailField(unique=True, null=True, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='MEDIUM')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ENQUIRY', help_text="Current status of the lead")
    program = models.TextField(blank=True, null=True, help_text="Enter the program name")
    remarks = models.TextField(blank=True, null=True, help_text="Additional notes or comments about the lead")
    location = models.CharField(max_length=100, blank=True, null=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, blank=True, null=True)
    custom_source = models.CharField(max_length=50, blank=True, null=True)
    created_by = models.ForeignKey(User,on_delete=models.SET_NULL,null=True, blank=True,related_name='created_leads')
    # Processing workflow fields
    processing_status = models.CharField(max_length=20, choices=PROCESSING_STATUS_CHOICES, default='PENDING')
    processing_executive = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        limit_choices_to={'role': 'PROCESSING'}, related_name='processing_leads'
    )
    processing_status_date = models.DateTimeField(auto_now_add=True, db_index=True)
    processing_notes = models.TextField(blank=True, null=True)

    # Document tracking
    document_status = models.CharField(max_length=20, choices=DOCUMENT_STATUS_CHOICES, default='PENDING')
    documents_received = models.TextField(blank=True, null=True)

    # Two-level assignment tracking
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assigned_leads',
        help_text="Primary assignee (Manager/Department Head)"
    )
    assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='leads_assigned_by_me',
        help_text="Who assigned this lead"
    )
    assigned_date = models.DateTimeField(null=True, blank=True)
    
    # Secondary assignment for junior staff
    sub_assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='sub_assigned_leads',
        help_text="Junior employee handling the lead"
    )
    sub_assigned_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='leads_sub_assigned_by_me',
        help_text="Manager who sub-assigned to junior"
    )
    sub_assigned_date = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    registration_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-priority', '-created_at']
        verbose_name = 'Lead'
        verbose_name_plural = 'Leads'
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['priority']),
            models.Index(fields=['processing_status']),
            models.Index(fields=['assigned_to']),
            models.Index(fields=['sub_assigned_to']),
        ]

    def __str__(self):
        return f"{self.name} ({self.phone}) - {self.status}"

    def save(self, *args, **kwargs):
        # Update registration date when status changes to REGISTERED
        if self.status == 'REGISTERED' and not self.registration_date:
            self.registration_date = timezone.now()
        
        # Update processing status date when processing status changes
        if self.pk:
            original = Lead.objects.get(pk=self.pk)
            if original.processing_status != self.processing_status:
                self.processing_status_date = timezone.now()
        
        super().save(*args, **kwargs)

    def update_processing_status(self, status, executive=None, notes=''):
        """Helper method to update processing status with proper tracking"""
        self.processing_status = status
        self.processing_status_date = timezone.now()
        
        if executive and executive.role == 'PROCESSING':
            self.processing_executive = executive
        
        if notes:
            self.processing_notes = notes
        
        self.save()

    def get_processing_timeline(self):
        """Returns a queryset of processing status changes"""
        return self.processing_updates.all().order_by('-timestamp')
    
    # Get current handler of the lead
    @property
    def current_handler(self):
        """Returns the current person handling this lead (sub_assigned_to if exists, else assigned_to)"""
        return self.sub_assigned_to if self.sub_assigned_to else self.assigned_to

    @property
    def is_forwardable(self):
        """Check if lead can be forwarded to processing"""
        return (self.status == 'REGISTERED' and 
                self.processing_status in ['PENDING', 'REJECTED'])

    @property
    def is_acceptable(self):
        """Check if processing executive can accept this lead"""
        return self.processing_status == 'FORWARDED'

    @property
    def is_completable(self):
        """Check if processing can be marked as complete"""
        return (self.processing_status == 'PROCESSING' and 
                self.processing_executive is not None)


class LeadAssignment(models.Model):
    """Track all lead assignments and reassignments"""
    ASSIGNMENT_TYPE_CHOICES = [
        ('PRIMARY', 'Primary Assignment'),
        ('SUB', 'Sub Assignment'),
        ('REASSIGNMENT', 'Reassignment'),
    ]
    
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='assignment_history')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='received_assignments')
    assigned_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='made_assignments')
    assignment_type = models.CharField(max_length=20, choices=ASSIGNMENT_TYPE_CHOICES)
    notes = models.TextField(blank=True, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.lead} assigned to {self.assigned_to} by {self.assigned_by}"


class ProcessingUpdate(models.Model):
    """Model to track processing status changes"""
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='processing_updates')
    status = models.CharField(max_length=20, choices=Lead.PROCESSING_STATUS_CHOICES)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    notes = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.lead} - {self.get_status_display()} at {self.timestamp}"


class RemarkHistory(models.Model):
    """History of remarks edits for a lead"""
    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name='remark_history')
    previous_remarks = models.TextField(blank=True, null=True)
    new_remarks = models.TextField(blank=True, null=True)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f"Remarks changed for {self.lead} at {self.changed_at}"




class FollowUp(models.Model):

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('contacted', 'Contacted'),
        ('not_interested', 'Not Interested'),
        ('rescheduled', 'Rescheduled'),
    ]

    PRIORITY_CHOICES = [
        ('high', 'High'),
        ('medium', 'Medium'),
        ('low', 'Low'),
    ]

    FOLLOWUP_TYPE_CHOICES = [
        ('call', 'Call'),
        ('whatsapp', 'WhatsApp'),
        ('email', 'Email'),
        ('meeting', 'Meeting'),
    ]

    lead = models.ForeignKey(
        'Lead',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='followups'
    )


    phone_number = models.CharField(max_length=20)
    name = models.CharField(max_length=150, blank=True, null=True)


    follow_up_date = models.DateField()
    follow_up_time = models.TimeField(blank=True, null=True)


    followup_type = models.CharField(
        max_length=20,
        choices=FOLLOWUP_TYPE_CHOICES,
        default='call'
    )
    notes = models.TextField(blank=True)

    priority = models.CharField(
        max_length=10,
        choices=PRIORITY_CHOICES,
        default='medium'
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    assigned_to = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='followups'
    )

    converted_to_lead = models.BooleanField(default=False)
    converted_at = models.DateTimeField(blank=True, null=True)

    reminder_sent_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['follow_up_date', 'follow_up_time']
        indexes = [
            models.Index(fields=['follow_up_date']),
            models.Index(fields=['status']),
            models.Index(fields=['assigned_to']),
        ]

    def __str__(self):
        display = self.name or self.phone_number
        return f"{display} — {self.follow_up_date}"

    def save(self, *args, **kwargs):
        # Track conversion time
        if self.converted_to_lead and not self.converted_at:
            self.converted_at = timezone.now()

        # Track status changes for history
        if self.pk:
            original = FollowUp.objects.get(pk=self.pk)
            if original.status != self.status:
                FollowUpHistory.objects.create(
                    followup=self,
                    old_status=original.status,
                    new_status=self.status,
                    changed_by=self.assigned_to
                )

        super().save(*args, **kwargs)

    @property
    def is_overdue(self):
        return (
            self.status == 'pending' and
            self.follow_up_date < timezone.now().date()
        )

    @property
    def contact_display(self):
        if self.lead:
            return f"{self.lead.name} ({self.lead.phone})"
        return self.name or self.phone_number



class FollowUpHistory(models.Model):
    followup = models.ForeignKey(
        FollowUp,
        on_delete=models.CASCADE,
        related_name='history'
    )

    old_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)

    changed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    notes = models.TextField(blank=True, null=True)

    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-changed_at']

    def __str__(self):
        return f"{self.followup} | {self.old_status} → {self.new_status}"