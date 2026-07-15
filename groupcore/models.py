from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError



# Create your models here.

class MemberProfile(AbstractUser):
    ROLE_CHOICES = [
        ('MEMBER', 'Member'),
        ('TREASURER', 'Treasurer'),
        ('CHAIRMAN', 'Chairman'),
        ('VICE_CHAIRMAN', 'Vice Chairman'),
        ('SECRETARY', 'Secretary'),
        ('MOBILIZER', 'Mobilizer'),
        ('OVERSEER', 'Overseer'),
    ]

    role = models.CharField(max_length=15, choices=ROLE_CHOICES, default='MEMBER')

    
    phone_number = models.CharField(max_length=20, blank=True, null=True)
    next_of_kin_name = models.CharField(max_length=100, blank=True, null=True)
    next_of_kin_contact = models.CharField(max_length=20, blank=True, null=True)
    profile_picture = models.ImageField(upload_to='profile_pics/', blank=True, null=True)
    

    def is_member(self):
        return self.role == 'MEMBER'

    def is_treasurer(self):
        return self.role == 'TREASURER'

    def is_chairman(self):
        return self.role == 'CHAIRMAN'

    def is_vice_chairman(self):
        return self.role == 'VICE_CHAIRMAN'
    
    def is_secretary(self):
        return self.role == 'SECRETARY'
    
    def is_mobilizer(self):
        return self.role == 'MOBILIZER'

    def is_overseer(self):
        return self.role == 'OVERSEER'

    def __str__(self):
        return self.username
    
class GroupSettings(models.Model):
    week_one_start = models.DateField(help_text="The date of the first week (Week 1)")

    @classmethod
    def get_active(cls):
        return cls.objects.order_by('pk').first()

    def clean(self):
        super().clean()
        if self.week_one_start and self.week_one_start.weekday() != 4:
            raise ValidationError({
                'week_one_start': 'Week 1 start must be a Friday.',
            })
        if GroupSettings.objects.exclude(pk=self.pk).exists():
            raise ValidationError("Only one group setting record is allowed.")

    def save(self, *args, **kwargs):
        if self.pk is None:
            existing = GroupSettings.get_active()
            if existing:
                self.pk = existing.pk
                kwargs.pop('force_insert', None)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Group Settings (Week 1 Start: {self.week_one_start})"

    class Meta:
        verbose_name = "Group Setting"
        verbose_name_plural = "Group Settings"


class SavingsAccount(models.Model):
    owner = models.ForeignKey(MemberProfile, on_delete=models.CASCADE, related_name='savings_accounts')
    label = models.CharField(max_length=100, help_text="e.g. A, B, C, or an account/member name")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('owner', 'label')
        ordering = ['owner__username', 'label']

    def __str__(self):
        return f"{self.owner.username} - Account {self.label}"
