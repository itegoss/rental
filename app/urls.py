from django.contrib import admin
from django.urls import path
from app import views 
from .views import payment
urlpatterns = [
   
    path('', views.index, name='index'),  
    path('logout/', views.logout, name='logout'),
    path('signup/', views.signup, name='signup'),
    path('signin/', views.signin, name='signin'),
    path('forgot-username/', views.forgot, name='forgot'),
    path('resetpass/<str:username>/', views.resetpass, name='resetpass'),
    path('items/', views.items, name='items'),
    path('buy/<int:item_id>/', views.buy, name='buy'),
    path('userdetail/', views.userdetail, name='userdetail'),
    path('success/<int:rental_id>/', views.success, name='success'),  
    path('about/', views.about, name='about'),
    path('send-overdue-emails/', views.send_overdue_emails, name='send_overdue_emails'),
    path('buy/<int:item_id>/', views.buy, name='buy'),
    path('select-delivery/<int:pk>/', views.select_delivery, name='select_delivery'),
    path('payment/<int:rental_id>/', views.payment, name='payment'),
    path('payment/success/<int:rental_id>/', views.success, name='success'),
    path('paymentmethod/', views.paymentmethod, name='paymentmethod'),
    path('generate_receipt/',views.generate_receipt, name='generate_receipt'),
    path("approve-order/<str:order_id>/", views.approve_order, name="approve_order"),
    path("terms/", views.terms, name="terms"),
    path("services/", views.services, name="services"),
    

]
