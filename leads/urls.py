from django.urls import path
from .views import (
    LeadListView,
    LeadCreateView,
    LeadDetailView,
    LeadProcessingTimelineView,
    LeadAssignView,
    BulkLeadAssignView,
    LeadAssignmentHistoryView,
    MyTeamLeadsView,
    AvailableUsersForAssignmentView,
    UnassignLeadView,
    UpdateLeadView,
    BulkLeadUploadView,
    TodayLeadsAPI,
    FollowUpListCreateAPIView,
    FollowUpDetailAPIView,
    TodayFollowUpsAPIView,
    OverdueFollowUpsAPIView,
    LeadConversionDetailView,
)

urlpatterns = [
    # ── Leads ────────────────────────────────────────────────
    path('leads/', LeadListView.as_view(), name='lead-list'),
    path('leads/create/', LeadCreateView.as_view(), name='lead-create'),
    path('leads/assign/', LeadAssignView.as_view(), name='lead-assign'),
    path('leads/bulk-upload/', BulkLeadUploadView.as_view(), name='lead-bulk-upload'),
    path('leads/bulk-assign/', BulkLeadAssignView.as_view(), name='bulk-lead-assign'),
    path('leads/unassign/', UnassignLeadView.as_view(), name='lead-unassign'),
    path('leads/my-team/', MyTeamLeadsView.as_view(), name='my-team-leads'),
    path('leads/available-users/', AvailableUsersForAssignmentView.as_view(), name='available-users'),

    # ── Lead detail (pk) — must come after all /leads/static-paths/
    path('leads/<int:pk>/', LeadDetailView.as_view(), name='lead-detail'),
    path('leads/<int:pk>/update/', UpdateLeadView.as_view(), name='lead-update'),
    path('leads/<int:lead_id>/timeline/', LeadProcessingTimelineView.as_view(), name='lead-timeline'),
    path('leads/<int:lead_id>/assignment-history/', LeadAssignmentHistoryView.as_view(), name='lead-assignment-history'),
    path('leads/<int:lead_id>/conversion/', LeadConversionDetailView.as_view(), name='lead-conversion'),

    # ── Today's Leads ─────────────────────────────────────────
    path('today-leads/', TodayLeadsAPI.as_view(), name='today-leads'),

    # ── Follow-ups — specific paths BEFORE <int:pk> ──────────
    path('followups/', FollowUpListCreateAPIView.as_view(), name='followup-list-create'),
    path('followups/today/', TodayFollowUpsAPIView.as_view(), name='followups-today'),
    path('followups/overdue/', OverdueFollowUpsAPIView.as_view(), name='followups-overdue'),
    path('followups/<int:pk>/', FollowUpDetailAPIView.as_view(), name='followup-detail'),
]