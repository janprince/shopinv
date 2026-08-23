from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.ShopLoginView.as_view(), name="login"),
    path("logout/", views.ShopLogoutView.as_view(), name="logout"),
    path("profile/", views.profile, name="profile"),
    path("profile/password/", views.change_password, name="change_password"),
    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/password/", views.user_reset_password, name="user_reset_password"),
    path("users/<int:pk>/toggle/", views.user_toggle_active, name="user_toggle_active"),
]
