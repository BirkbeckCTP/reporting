from django.conf.urls import url

from plugins.reporting import views

urlpatterns = [
    url(r'^$',
        views.index,
        name='reporting_index'),
    url(r'^press/$',
        views.press,
        name='reporting_press'),
    url(r'^by_month/$',
        views.report_journal_usage_by_month,
        name='reporting_journal_usage_by_month'),
    url(r'^articles/(?P<journal_id>\d+)/$',
        views.report_articles,
        name='reporting_articles'),
    url(r'^production/$',
        views.report_production,
        name='reporting_production'),
    url(r'^geo/$',
        views.report_geo,
        name='reporting_geo'),
    url(r'^geo/(?P<journal_id>\d+)/$',
        views.report_geo,
        name='report_geo_journal'),
]
