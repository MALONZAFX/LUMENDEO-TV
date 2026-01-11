# myapp/decorators.py
from django.shortcuts import redirect
from django.contrib import messages

def admin_required(view_func):
    """Decorator to ensure user is admin (Amos or Mesh)"""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.error(request, 'Please login first.')
            return redirect('dashboard_login')
        
        # Check if user is Amos or Mesh or is staff
        if request.user.username not in ['Amos', 'Mesh'] and not request.user.is_staff:
            messages.error(request, 'Admin access required.')
            return redirect('home')
        
        return view_func(request, *args, **kwargs)
    
    return wrapper