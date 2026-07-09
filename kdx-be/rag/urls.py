from django.urls import path, include
from . import views


urlpatterns = [
    path("common/", views.CommonView.as_view(), name='common rag view'),
    path("query/", views.RAGQueryView.as_view(), name='rag query view'),
]
