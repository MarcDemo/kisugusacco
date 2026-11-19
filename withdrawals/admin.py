from django.contrib import admin

from .models import Withdrawal, WithdrawalRevision


class WithdrawalRevisionInline(admin.TabularInline):
    model = WithdrawalRevision
    extra = 0
    readonly_fields = [
        'revision_number', 'before_data', 'after_data', 'reason', 'edited_by', 'edited_at'
    ]
    can_delete = False


@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = ['member', 'account', 'amount', 'withdrawn_on', 'is_voided', 'recorded_by']
    list_filter = ['is_voided', 'withdrawn_on']
    search_fields = ['member__username', 'account__label', 'reference']
    readonly_fields = [
        'member', 'account', 'amount', 'withdrawn_on', 'reason', 'reference',
        'notes', 'recorded_by', 'created_at', 'updated_at', 'is_voided',
        'void_reason', 'voided_by', 'voided_at',
    ]
    inlines = [WithdrawalRevisionInline]

    def has_delete_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False


