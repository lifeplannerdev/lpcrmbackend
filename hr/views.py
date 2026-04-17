from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import get_user_model
from .models import Penalty, AttendanceDocument, Candidate
from .serializers import (
    PenaltySerializer, 
    AttendanceDocumentSerializer, 
    StaffSerializer,
    CandidateSerializer
)
from .permissions import IsHR, IsHROrAccountsOrAdmin

User = get_user_model()


# PENALTY APIs 

class PenaltyListCreateAPI(APIView):
    permission_classes = [IsHROrAccountsOrAdmin]
    
    def get(self, request):
        penalties = Penalty.objects.all()
        
        # Filter by month
        month = request.GET.get("month")
        if month:
            penalties = penalties.filter(month=month)
        
        # Filter by user
        user_id = request.GET.get("user")
        if user_id:
            penalties = penalties.filter(user_id=user_id)
        
        # Serialize with user details
        serializer = PenaltySerializer(
            penalties.order_by("-date"), 
            many=True
        )
        
        return Response({
            "count": penalties.count(),
            "results": serializer.data
        })
    
    def post(self, request):
        serializer = PenaltySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PenaltyDetailAPI(APIView):
    permission_classes = [IsHROrAccountsOrAdmin]
    
    def get(self, request, pk):
        try:
            penalty = Penalty.objects.get(pk=pk)
        except Penalty.DoesNotExist:
            return Response(
                {"error": "Penalty not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = PenaltySerializer(penalty)
        return Response(serializer.data)
    
    def put(self, request, pk):
        try:
            penalty = Penalty.objects.get(pk=pk)
        except Penalty.DoesNotExist:
            return Response(
                {"error": "Penalty not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = PenaltySerializer(penalty, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def delete(self, request, pk):
        try:
            penalty = Penalty.objects.get(pk=pk)
        except Penalty.DoesNotExist:
            return Response(
                {"error": "Penalty not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        penalty.delete()
        return Response(
            {"message": "Penalty deleted successfully"}, 
            status=status.HTTP_204_NO_CONTENT
        )


# ATTENDANCE APIs 
class AttendanceDocumentAPI(APIView):

    permission_classes = [IsHR]
    
    def get(self, request):
        docs = AttendanceDocument.objects.all()
        month = request.GET.get("month")
        if month:
            docs = docs.filter(month=month)
        
        serializer = AttendanceDocumentSerializer(docs.order_by("-date"), many=True)
        return Response({
            "count": docs.count(),
            "results": serializer.data
        })
    
    def post(self, request):
        serializer = AttendanceDocumentSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



class AttendanceDocumentDeleteAPI(APIView):
    permission_classes = [IsHR] 
    def get(self, request, pk):
        try:
            doc = AttendanceDocument.objects.get(pk=pk)
        except AttendanceDocument.DoesNotExist:
            return Response(
                {"error": "Document not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = AttendanceDocumentSerializer(doc)
        return Response(serializer.data)
    
    def delete(self, request, pk):
        try:
            doc = AttendanceDocument.objects.get(pk=pk)
        except AttendanceDocument.DoesNotExist:
            return Response(
                {"error": "Document not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        doc.delete()
        return Response(
            {"message": "Document deleted successfully"}, 
            status=status.HTTP_204_NO_CONTENT
        )


# STAFF/EMPLOYEE APIs
class StaffListAPI(APIView):
    permission_classes = [IsHROrAccountsOrAdmin]
    
    def get(self, request):
        users = User.objects.all()
        
        # Filter by role
        role = request.GET.get("role")
        if role:
            users = users.filter(role=role)
        
        # Filter by active status
        is_active = request.GET.get("is_active")
        if is_active is not None:
            users = users.filter(is_active=is_active.lower() == "true")
        
        # Search
        search = request.GET.get("search")
        if search:
            users = users.filter(
                first_name__icontains=search
            ) | users.filter(
                last_name__icontains=search
            ) | users.filter(
                username__icontains=search
            ) | users.filter(
                email__icontains=search
            )
        
        serializer = StaffSerializer(users.order_by("first_name"), many=True)
        return Response({
            "count": users.count(),
            "results": serializer.data
        })


class StaffDetailAPI(APIView):
    permission_classes = [IsHROrAccountsOrAdmin]
    
    def get(self, request, pk):
        try:
            user = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response(
                {"error": "Employee not found"}, 
                status=status.HTTP_404_NOT_FOUND
            )
        
        serializer = StaffSerializer(user)
        return Response(serializer.data)


class CandidateListCreateAPI(APIView):
    permission_classes = [IsHROrAccountsOrAdmin]

    def get(self, request):
        status_filter = request.GET.get("status")
        candidates = Candidate.objects.all()

        if status_filter:
            candidates = candidates.filter(status=status_filter)

        serializer = CandidateSerializer(candidates, many=True)
        return Response({
            "count": candidates.count(),
            "results": serializer.data
        })

    def post(self, request):
        serializer = CandidateSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)


class CandidateDetailAPI(APIView):
    permission_classes = [IsHROrAccountsOrAdmin]

    def get(self, request, pk):
        try:
            candidate = Candidate.objects.get(pk=pk)
        except Candidate.DoesNotExist:
            return Response({"error": "Not found"}, status=404)

        return Response(CandidateSerializer(candidate).data)

    def put(self, request, pk):
        candidate = Candidate.objects.get(pk=pk)
        serializer = CandidateSerializer(candidate, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)

        return Response(serializer.errors, status=400)

    def delete(self, request, pk):
        candidate = Candidate.objects.get(pk=pk)
        candidate.delete()
        return Response(status=204)

