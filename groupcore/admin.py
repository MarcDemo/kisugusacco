from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import MemberProfile, GroupSettings, SavingsAccount
# Register your models here.

class MemberProfileAdmin(UserAdmin):
    model = MemberProfile
    list_display = ('username', 'email', 'role', 'is_staff', 'is_active')
    list_filter = ('role', 'is_staff', 'is_active')
    search_fields = ('username', 'email')

    fieldsets = UserAdmin.fieldsets + (
        ('Extra Info', {'fields': ('role', 'phone_number', 'next_of_kin_name', 'next_of_kin_contact', 'profile_picture')}),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Extra Info', {'fields': ('role', 'phone_number', 'next_of_kin_name', 'next_of_kin_contact')}),
    )

admin.site.register(MemberProfile, MemberProfileAdmin)


@admin.register(GroupSettings)
class GroupSettingsAdmin(admin.ModelAdmin):
    list_display = ('week_one_start',)

    def has_add_permission(self, request):
        return not GroupSettings.objects.exists()


admin.site.register(SavingsAccount)
