"""
URL configuration for the chatbot application.
"""

from django.urls import path
from . import views

urlpatterns = [
    path("", views.select_college, name="select"),
    path("enter/", views.enter_chat, name="enter"),
    path("chat/", views.chat_page, name="chat"),
    path("change/", views.change_college, name="change"),
    path("api/chat/", views.chatbot, name="chatbot"),
]
