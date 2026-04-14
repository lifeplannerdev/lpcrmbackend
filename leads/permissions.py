from rest_framework.permissions import BasePermission


FULL_ACCESS_ROLES = ['ADMIN', 'CEO', 'OPS']


MANAGER_ROLES = [
    'ADM_MANAGER',
    'ADM_COUNSELLOR',
    'CM',
    'BDM',
]


EXECUTIVE_ROLES = [
    'ADM_EXEC',
    'FOE',
]


NON_LEAD_ROLES = [
    'PROCESSING',
    'MEDIA',
    'TRAINER',
    'HR',
    'ACCOUNTS',
    'DOCUMENTATION'
]

LEAD_ACCESS_ROLES = FULL_ACCESS_ROLES + MANAGER_ROLES + EXECUTIVE_ROLES


LEAD_VIEW_ALL_ROLES = FULL_ACCESS_ROLES


class CanAccessLeads(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role in LEAD_ACCESS_ROLES
        )


class CanAssignLeads(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return (
            user.is_authenticated and
            user.role in LEAD_ACCESS_ROLES
        )


class CanViewAllLeads(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role in LEAD_VIEW_ALL_ROLES
        )


class CanModifyAllLeads(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role in FULL_ACCESS_ROLES
        )

CONVERSION_ROLES = ['ADMIN', 'OPS', 'CM', 'CEO', 'BUSINESS_HEAD']

class CanManageConversion(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            request.user.role in CONVERSION_ROLES
        )