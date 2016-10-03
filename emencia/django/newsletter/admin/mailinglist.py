# -*- coding: utf_8 -*-
"""ModelAdmin for MailingList"""
from datetime import datetime

from django.contrib import admin
from django.conf.urls.defaults import url
from django.conf.urls.defaults import patterns
from django.core.urlresolvers import reverse
from django.shortcuts import get_object_or_404
from django.utils.translation import ugettext as _
from django.http import HttpResponseRedirect
from django.contrib.admin.views.main import ChangeList
from mezzanine.utils.views import render, paginate

from emencia.django.newsletter.admin.contact import ContactAdmin
from emencia.django.newsletter.models import Contact
from emencia.django.newsletter.models import MailingList
from emencia.django.newsletter.settings import USE_WORKGROUPS
from emencia.django.newsletter.utils.workgroups import request_workgroups
from emencia.django.newsletter.utils.workgroups import request_workgroups_contacts_pk
from emencia.django.newsletter.utils.workgroups import request_workgroups_mailinglists_pk
from emencia.django.newsletter.utils.vcard import vcard_contacts_export_response
from django.contrib import messages
import urllib


class MailingListAdmin(admin.ModelAdmin):
    date_hierarchy = 'creation_date'
    list_display = ('creation_date', 'name', 'description',
                    'subscribers_count', 'unsubscribers_count',
                    'exportation_link', 'management_link',)
    list_editable = ('name', 'description')
    list_filter = ('creation_date', 'modification_date')
    search_fields = ('name', 'description',)
    #filter_horizontal = ['subscribers', 'unsubscribers']
    fieldsets = ((None, {'fields': ('name', 'description',)}),
                 #(None, {'fields': ('subscribers',)}),
                 #(None, {'fields': ('unsubscribers',)}),
                 )
    actions = ['merge_mailinglist']
    actions_on_top = False
    actions_on_bottom = True

    def queryset(self, request):
        queryset = super(MailingListAdmin, self).queryset(request)
        if not request.user.is_superuser and USE_WORKGROUPS:
            mailinglists_pk = request_workgroups_mailinglists_pk(request)
            queryset = queryset.filter(pk__in=mailinglists_pk)
        return queryset

    def save_model(self, request, mailinglist, form, change):
        workgroups = []
        if not mailinglist.pk and not request.user.is_superuser:
            workgroups = request_workgroups(request)
        mailinglist.save()
        for workgroup in workgroups:
            workgroup.mailinglists.add(mailinglist)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if 'subscribers' in db_field.name and not request.user.is_superuser:
            contacts_pk = request_workgroups_contacts_pk(request)
            kwargs['queryset'] = Contact.objects.filter(pk__in=contacts_pk)
        return super(MailingListAdmin, self).formfield_for_manytomany(
            db_field, request, **kwargs)

    def merge_mailinglist(self, request, queryset):
        """Merge multiple mailing list"""
        if queryset.count() == 1:
            self.message_user(request, _('Please select a least 2 mailing list.'))
            return None

        subscribers = {}
        unsubscribers = {}
        for ml in queryset:
            for contact in ml.subscribers.all():
                subscribers[contact] = ''
            for contact in ml.unsubscribers.all():
                unsubscribers[contact] = ''

        when = str(datetime.now()).split('.')[0]
        new_mailing = MailingList(name=_('Merging list at %s') % when,
                                  description=_('Mailing list created by merging at %s') % when)
        new_mailing.save()
        new_mailing.subscribers = subscribers.keys()
        new_mailing.unsubscribers = unsubscribers.keys()

        self.message_user(request, _('%s succesfully created by merging.') % new_mailing)
        return HttpResponseRedirect(reverse('admin:newsletter_mailinglist_change',
                                            args=[new_mailing.pk]))
    merge_mailinglist.short_description = _('Merge selected mailinglists')

    def exportation_link(self, mailinglist):
        """Display link for exportation"""
        return '<a href="%s">%s</a>' % (reverse('admin:newsletter_mailinglist_export',
                                                args=[mailinglist.pk]),
                                        _('Export Subscribers'))
    exportation_link.allow_tags = True
    exportation_link.short_description = _('Export')

    def management_link(self, mailinglist):
        """Display link for subscriber management"""
        return '<a href="%s">%s</a>' % (reverse('admin:newsletter_mailinglist_manage',
                                                args=[mailinglist.pk]),
                                        _('Manage Subscribers'))
    management_link.allow_tags = True
    management_link.short_description = _('Subscribers')

    def export_subscribers(self, request, mailinglist_id):
        """Export subscribers in the mailing in VCard"""
        mailinglist = get_object_or_404(MailingList, pk=mailinglist_id)
        name = 'contacts_%s' % mailinglist.name
        return vcard_contacts_export_response(mailinglist.subscribers.all(), name)

    def get_urls(self):
        urls = super(MailingListAdmin, self).get_urls()
        my_urls = patterns('',
                           url(r'^export/(?P<mailinglist_id>\d+)/$',
                               self.admin_site.admin_view(self.export_subscribers),
                               name='newsletter_mailinglist_export'),
                           url(r'^manage/(?P<mailinglist_id>\d+)/$',
                               self.admin_site.admin_view(self.manage_subscribers),
                               name='newsletter_mailinglist_manage'),
                           url(r'^manage/(?P<mailinglist_id>\d+)/add/$',
                               self.admin_site.admin_view(self.add_subscriber),
                               name='newsletter_mailinglist_add'),
                           url(r'^manage/(?P<mailinglist_id>\d+)/unsub/(?P<subscriber_id>\d+)/$',
                               self.admin_site.admin_view(self.unsubscribe),
                               name='newsletter_mailinglist_unsub'),
                           url(r'^manage/(?P<mailinglist_id>\d+)/sub/(?P<subscriber_id>\d+)/$',
                               self.admin_site.admin_view(self.subscribe),
                               name='newsletter_mailinglist_sub'),
                           url(r'^manage/(?P<mailinglist_id>\d+)/remove/(?P<subscriber_id>\d+)/$',
                               self.admin_site.admin_view(self.remove),
                               name='newsletter_mailinglist_remove'),
        )
        return my_urls + urls

    def manage_subscribers(self, request, mailinglist_id):
        mailinglist = get_object_or_404(MailingList, pk=mailinglist_id)

        # filters
        q = request.GET.get("q", "")
        is_sub = request.GET.get("subscriber", 0)
        page = request.GET.get("page", "1")

        # urls for things
        base_url = "?"
        filter_url = base_url
        if q:
            filter_url = "?q=%s&" % urllib.quote_plus(q)

        subscribers = mailinglist.subscribers.all()
        unsubscribers = mailinglist.unsubscribers.all()

        full_result_count = subscribers.count() + unsubscribers.count()

        if q:
            subscribers = subscribers.filter(email__icontains=q)
            unsubscribers = unsubscribers.filter(email__icontains=q)

        if is_sub == "1":
            unsubscribers = []
        elif is_sub == "2":
            subscribers = []

        result_count = len(subscribers) + len(unsubscribers)

        contacts = [x for x in subscribers] + [x for x in unsubscribers]
        contacts = list(set(contacts))

        context = dict(
            title=u"Manage subscribers for '%s'" % mailinglist,
            mailinglist=mailinglist,
            unsubscribers=unsubscribers,
            subscribers=paginate(contacts, request.GET.get("page", 1), 30, 10),
            result_count=result_count,
            filter_url=filter_url,
            is_sub=is_sub,
            full_result_count=full_result_count
        )
        return render(request, "admin/newsletter/mailinglist/manage_subscribers.html", context)

    def switch_sub(self, original, new, object):
        original.remove(object)
        new.add(object)

    def unsubscribe(self, request, mailinglist_id, subscriber_id):
        mailinglist = get_object_or_404(MailingList, pk=mailinglist_id)
        contact = mailinglist.subscribers.get(pk=subscriber_id)
        self.swtich_sub(mailinglist.subscribers, mailinglist.unsubscribers, contact)

        messages.add_message(request, messages.INFO, "User '%s' was unsubscribed from this mailing list." % contact.email)
        return HttpResponseRedirect(request.META.get('HTTP_REFERER'))

    def subscribe(self, request, mailinglist_id, subscriber_id):
        mailinglist = get_object_or_404(MailingList, pk=mailinglist_id)
        contact = mailinglist.subscribers.get(pk=subscriber_id)
        self.swtich_sub(mailinglist.unsubscribers, mailinglist.subscribers, contact)

        messages.add_message(request, messages.INFO, "User '%s' was subscribed to this mailing list." % contact.email)
        return HttpResponseRedirect(request.META.get('HTTP_REFERER'))

    def remove(self, request, mailinglist_id, subscriber_id):
        mailinglist = get_object_or_404(MailingList, pk=mailinglist_id)
        try:
            contact = mailinglist.subscribers.get(pk=subscriber_id)
            mailinglist.subscribers.remove(contact)
        except:
            pass

        try:
            contact = mailinglist.unsubscribers.get(pk=subscriber_id)
            mailinglist.unsubscribers.remove(contact)
        except:
            pass

        messages.add_message(request, messages.INFO, "User '%s' was removed from this mailing list." % contact.email)
        return HttpResponseRedirect(request.META.get('HTTP_REFERER'))

    def add_subscriber(self, request, mailinglist_id):
        mailinglist = get_object_or_404(MailingList, pk=mailinglist_id)

        contact_id = request.GET.get("contact_id", "")
        if contact_id:
            contact = get_object_or_404(Contact, pk=contact_id)

            # check if already subscribed
            test = mailinglist.subscribers.filter(pk=contact_id) or mailinglist.unsubscribers.filter(pk=contact_id)

            if not test:
                if request.GET.get("unsub", ""):
                    mailinglist.unsubscribers.add(contact)
                else:
                    mailinglist.subscribers.add(contact)
                messages.add_message(request, messages.INFO,
                                     "User '%s' was added to mailing list." % contact.email)
            else:
                messages.add_message(request, messages.WARNING,
                                     "User '%s' was already in the mailing list." % contact.email)

        context = dict(
            title=u"Add subscriber for '%s'" % mailinglist,
            mailinglist=mailinglist,
            available_contacts=Contact.objects.exclude(pk__in=mailinglist.subscribers.all()).exclude(pk__in=mailinglist.unsubscribers.all())
        )
        return render(request, "admin/newsletter/mailinglist/add_subscribers.html", context)