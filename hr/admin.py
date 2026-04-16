from django.contrib import admin
from .models import Penalty,AttendanceDocument,Candidate
# Register your models here.

@admin.register(Penalty)
class PenaltyAdmin(admin.ModelAdmin):
    list_display = ['user', 'act', 'amount', 'month', 'date']
    list_filter = ['month', 'date', 'user']
    search_fields = ['user__username', 'act']
    date_hierarchy = 'date'

@admin.register(AttendanceDocument)
class AttendanceDocumentAdmin(admin.ModelAdmin):
    list_display = ['name', 'date', 'month', 'uploaded_at']
    list_filter = ['month', 'date']
    search_fields = ['name']

admin.site.register(Candidate)
