from django.contrib import admin
from .models import Lead,ProcessingUpdate,RemarkHistory,LeadAssignment,FollowUp,FollowUpHistory,LeadConversionDetail

admin.site.register(Lead)
admin.site.register(ProcessingUpdate)
admin.site.register(RemarkHistory)
admin.site.register(LeadAssignment)
admin.site.register(FollowUp)
admin.site.register(FollowUpHistory)
admin.site.register(LeadConversionDetail)