from rest_framework import serializers
from .models import Penalty, AttendanceDocument,Candidate
from django.contrib.auth import get_user_model

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email", "role", "salary", "join_date", "phone", "location"]

class UserMinimalSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ["id", "username", "name", "first_name", "last_name", "email"]
    
    def get_name(self, obj):
        if obj.first_name and obj.last_name:
            return f"{obj.first_name} {obj.last_name}"
        elif obj.first_name:
            return obj.first_name
        return obj.username

class PenaltySerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField(read_only=True)
    user_email = serializers.SerializerMethodField(read_only=True)
    user_details = UserMinimalSerializer(source='user', read_only=True)
    
    class Meta:
        model = Penalty
        fields = [
            'id', 
            'user',           
            'user_name',      
            'user_email',    
            'user_details',  
            'act', 
            'amount', 
            'month', 
            'date'
        ]
    
    def get_user_name(self, obj):
        if not obj.user:
            return "Unknown"
        if obj.user.first_name and obj.user.last_name:
            return f"{obj.user.first_name} {obj.user.last_name}"
        elif obj.user.first_name:
            return obj.user.first_name
        return obj.user.username
    
    def get_user_email(self, obj):
        return obj.user.email if obj.user else ""

class AttendanceDocumentSerializer(serializers.ModelSerializer):
    document_url = serializers.SerializerMethodField(read_only=True)
    
    class Meta:
        model = AttendanceDocument
        fields = [
            "id",
            "name",
            "date",
            "month",
            "document",
            "document_url",
            "uploaded_at"
        ]
    
    def get_document_url(self, obj):
        if obj.document:
            return obj.document.url
        return None

class StaffSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    full_name = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "first_name",
            "last_name",
            "full_name",
            "email",
            "phone",
            "role",
            "role_display",
            "team",
            "location",
            "salary",
            "join_date",
            "is_active",
        ]
    
    def get_full_name(self, obj):
        if obj.first_name and obj.last_name:
            return f"{obj.first_name} {obj.last_name}"
        elif obj.first_name:
            return obj.first_name
        return obj.username


class CandidateSerializer(serializers.ModelSerializer):
    resume_url = serializers.SerializerMethodField()

    class Meta:
        model = Candidate
        fields = "__all__"

    def get_resume_url(self, obj):
        return obj.resume.url if obj.resume else None