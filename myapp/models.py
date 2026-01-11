# myapp/models.py
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta

def default_expire_date():
    return timezone.now() + timedelta(days=30)

class MonthlyVideo(models.Model):
    title = models.CharField(max_length=255)
    
    # LOCAL FILE STORAGE
    video = models.FileField(upload_to='videos/')
    trailer = models.FileField(upload_to='trailers/')
    thumbnail = models.ImageField(upload_to='thumbnails/')
    
    year_published = models.PositiveIntegerField()
    introduction = models.TextField()
    date_uploaded = models.DateTimeField(auto_now_add=True)
    expire_date = models.DateTimeField(default=default_expire_date)
    cast = models.CharField(max_length=150)
    theme = models.CharField(max_length=150)
    length = models.CharField(max_length=150, default='2.0')
    movie_type = models.CharField(max_length=150, default='drama')
    
    class Meta:
        ordering = ['-date_uploaded']
        verbose_name = 'Monthly Video'
        verbose_name_plural = 'Monthly Videos'

    def __str__(self):
        return self.title

    def is_expired(self):
        return timezone.now() > self.expire_date
    
    def get_intro_chunks(self):
        """Split introduction into 6-word chunks"""
        words = self.introduction.split()
        return [' '.join(words[i:i+6]) for i in range(0, len(words), 6)]
    
    # Helper methods to get file information
    def get_video_filename(self):
        """Get just the filename from the video path"""
        if self.video:
            return self.video.name.split('/')[-1]
        return ''
    
    def get_trailer_filename(self):
        """Get just the filename from the trailer path"""
        if self.trailer:
            return self.trailer.name.split('/')[-1]
        return ''
    
    def get_thumbnail_filename(self):
        """Get just the filename from the thumbnail path"""
        if self.thumbnail:
            return self.thumbnail.name.split('/')[-1]
        return ''

class Payment(models.Model):
    # Personal Information
    phone = models.CharField(max_length=15)
    name = models.CharField(max_length=100)
    email = models.EmailField(blank=True, null=True)  # Optional for M-Pesa
    
    # Payment Information
    amount = models.DecimalField(max_digits=10, decimal_places=2, default=10.00)
    movie = models.ForeignKey(MonthlyVideo, on_delete=models.CASCADE)
    status = models.BooleanField(default=False)
    timestamp = models.DateTimeField(default=timezone.now)
    
    # Paystack Integration Fields
    payment_reference = models.CharField(max_length=100, unique=True, blank=True, null=True)
    transaction_id = models.CharField(max_length=100, blank=True, null=True)
    payment_method = models.CharField(max_length=50, blank=True, null=True)
    error_message = models.TextField(blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    
    # Payment Status Choices
    PAYMENT_STATUS = (
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('refunded', 'Refunded'),
    )
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='pending')
    
    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Payment'
        verbose_name_plural = 'Payments'
        indexes = [
            models.Index(fields=['phone', 'status']),
            models.Index(fields=['timestamp']),
            models.Index(fields=['payment_reference']),
        ]

    def __str__(self):
        return f"{self.name} - {self.phone} - KES {self.amount} - {'Paid' if self.status else 'Pending'}"
    
    def mark_as_paid(self, transaction_id=None, payment_method=None):
        """Mark payment as successful"""
        self.status = True
        self.payment_status = 'success'
        self.paid_at = timezone.now()
        if transaction_id:
            self.transaction_id = transaction_id
        if payment_method:
            self.payment_method = payment_method
        self.save()
    
    def mark_as_failed(self, error_message=None):
        """Mark payment as failed"""
        self.status = False
        self.payment_status = 'failed'
        if error_message:
            self.error_message = error_message
        self.save()
    
    def is_paid(self):
        """Check if payment is completed"""
        return self.status and self.payment_status == 'success'
    
    def get_display_amount(self):
        """Get formatted amount"""
        return f"KES {self.amount:.2f}"
    
    def get_payment_duration(self):
        """Get time since payment was made"""
        if self.paid_at:
            duration = timezone.now() - self.paid_at
            minutes = duration.total_seconds() / 60
            
            if minutes < 1:
                return "Just now"
            elif minutes < 60:
                return f"{int(minutes)} minutes ago"
            elif minutes < 1440:  # 24 hours
                hours = minutes / 60
                return f"{int(hours)} hours ago"
            else:
                days = minutes / 1440
                return f"{int(days)} days ago"
        return "Not paid yet"

class AdminLogin(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    login_time = models.DateTimeField(auto_now_add=True)
    ip_address = models.CharField(max_length=50, blank=True)
    user_agent = models.TextField(blank=True)
    
    class Meta:
        ordering = ['-login_time']
        verbose_name = 'Admin Login'
        verbose_name_plural = 'Admin Logins'
    
    def __str__(self):
        return f"{self.user.username} - {self.login_time.strftime('%Y-%m-%d %H:%M')}"

class VideoView(models.Model):
    """Track video views"""
    video = models.ForeignKey(MonthlyVideo, on_delete=models.CASCADE)
    ip_address = models.CharField(max_length=50, blank=True)
    user_agent = models.TextField(blank=True)
    viewed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-viewed_at']
        verbose_name = 'Video View'
        verbose_name_plural = 'Video Views'
    
    def __str__(self):
        return f"{self.video.title} - {self.viewed_at.strftime('%Y-%m-%d %H:%M')}"

class PaymentAnalytics(models.Model):
    """Daily payment analytics"""
    date = models.DateField(unique=True)
    total_payments = models.IntegerField(default=0)
    successful_payments = models.IntegerField(default=0)
    failed_payments = models.IntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    average_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    class Meta:
        ordering = ['-date']
        verbose_name = 'Payment Analytics'
        verbose_name_plural = 'Payment Analytics'
    
    def __str__(self):
        return f"{self.date} - KES {self.total_revenue:.2f}"
    
    def update_analytics(self):
        """Update analytics based on today's payments"""
        from django.db.models import Count, Sum, Avg
        
        payments = Payment.objects.filter(
            timestamp__date=self.date
        )
        
        self.total_payments = payments.count()
        self.successful_payments = payments.filter(status=True).count()
        self.failed_payments = payments.filter(status=False).count()
        
        revenue_data = payments.filter(status=True).aggregate(
            total=Sum('amount'),
            average=Avg('amount')
        )
        
        self.total_revenue = revenue_data['total'] or 0
        self.average_payment = revenue_data['average'] or 0
        self.save()