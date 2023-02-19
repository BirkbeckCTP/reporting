import csv
import os
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
import datetime
from datetime import datetime

from django.urls import reverse
from django.utils import timezone
from django.conf import settings
from django.template.defaultfilters import strip_tags
from django.db.models import (
    DurationField,
    ExpressionWrapper,
    F,
    IntegerField,
    Min,
    Case,
    Count,
    Q,
    Subquery,
    Func,
    When,
    OuterRef
)
from django.db.models.functions import TruncMonth

from submission import models as sm
from metrics import models as mm
from core.files import serve_temp_file
from core import models as core_models
from utils.function_cache import cache
from journal import models as jm
from review import models as rm
from metrics import models as mm
from identifiers import models as id_models


def get_first_day(dt, d_years=0, d_months=0):
    # d_years, d_months are "deltas" to apply to dt
    y, m = dt.year + d_years, dt.month + d_months
    a, m = divmod(m - 1, 12)
    return date(y+a, m + 1, 1)


def get_last_day(dt):
    return get_first_day(dt, 0, 1) + timedelta(-1)


def get_start_and_end_date(request):
    d = date.today()
    start_date = request.GET.get('start_date', get_first_day(d))
    last_date = request.GET.get('end_date', get_last_day(d))

    return start_date, last_date


def get_first_month_year():
    return '{year}-{month}'.format(year=timezone.now().year, month='01')


def get_current_month_year():
    return '{year}-{month}'.format(
        year=timezone.now().year,
        month=timezone.now().strftime('%m'),
    )


def get_start_and_end_months(request):
    start_month = request.GET.get(
        'start_month', get_first_month_year()
    )

    end_month = request.GET.get(
        'end_month', get_current_month_year()
    )

    start_month_y, start_month_m = start_month.split('-')
    end_month_y, end_month_m = end_month.split('-')

    date_parts = {
        'start_month_m': start_month_m,
        'start_month_y': start_month_y,
        'end_month_m': end_month_m,
        'end_month_y': end_month_y,
        'start_unsplit': start_month,
        'end_unsplit': end_month,
    }

    return start_month, end_month, date_parts


def get_articles(journal, start_date, end_date):
    dt = timezone.now()

    f_editorial_delta = ExpressionWrapper(
        F('date_published') - F('date_submitted'),
        output_field=DurationField(),
    )

    articles = sm.Article.objects.filter(
        date_published__lte=dt,
    ).select_related(
        'section'
    ).annotate(editorial_delta=f_editorial_delta)

    if journal:
        articles = articles.filter(journal=journal)

    for article in articles:
        article.views = mm.ArticleAccess.objects.filter(
            article=article,
            accessed__gte=start_date,
            accessed__lte=end_date,
            type='view'
        )
        article.downloads = mm.ArticleAccess.objects.filter(
            article=article,
            accessed__gte=start_date,
            accessed__lte=end_date,
            type='download'
        )

    return articles


def get_accesses(journal, start_date, end_date):
    views = mm.ArticleAccess.objects.filter(
        article__journal=journal,
        type='view',
        accessed__gte=start_date,
        accessed__lte=end_date,
    ).count()

    downloads = mm.ArticleAccess.objects.filter(
        article__journal=journal,
        type='download',
        accessed__gte=start_date,
        accessed__lte=end_date,
    ).count()

    return views, downloads


def export_csv(rows):
    filename = '{0}.csv'.format(timezone.now())
    full_path = os.path.join(settings.BASE_DIR, 'files', 'temp', filename)

    with open(full_path, 'w') as csvfile:
        csv_writer = csv.writer(csvfile, delimiter=',')
        for row in rows:
            csv_writer.writerow(row)

    return serve_temp_file(
        full_path,
        filename
    )


def export_journal_csv(journals):
    all_rows = list()
    header_row = [
        'Name',
        'Views',
        'Downloads',
    ]
    all_rows.append(header_row)

    for journal in journals:
        row = [
            journal.name,
            journal.views,
            journal.downloads
        ]
        all_rows.append(row)

    return export_csv(all_rows)


def export_article_csv(articles, data):
    all_rows = list()

    info_header_row = [
        'Articles',
        'Submissions',
        'Published Articles',
        'Rejected Articles',
        'Views',
        'Downloads',
    ]
    all_rows.append(info_header_row)

    row = [
        data[0].get('articles').count(),
        data[0].get('submissions').count(),
        data[0].get('published_articles').count(),
        data[0].get('rejected_articles').count(),
        data[0].get('views').count(),
        data[0].get('downloads').count(),
    ]
    all_rows.append(row)

    main_header_row = [
        'ID',
        'Title',
        'Section',
        'Date Submitted',
        'Date Accepted',
        'Date Published',
        'Days to Publication'
        'Views',
        'Downloads',
    ]
    all_rows.append(main_header_row)

    for article in articles:
        row = [
            article.pk,
            strip_tags(article.title),
            article.section.name if article.section else 'No Section',
            article.date_submitted,
            article.date_accepted,
            article.date_published,
            article.editorial_delta.days if article.editorial_delta else '',
            article.views.count(),
            article.downloads.count(),
        ]
        all_rows.append(row)

    return export_csv(all_rows)


def export_production_csv(production_assignments):
    all_rows = list()
    header_row = [
        'Title',
        'Journal',
        'Typesetter',
        'Assigned',
        'Accepted',
        'Completed',
        'Time to Acceptance',
        'Time to Completion',
    ]
    all_rows.append(header_row)

    for assignment in production_assignments:
        row = [
            assignment.assignment.article.title,
            assignment.assignment.article.journal.code,
            assignment.typesetter,
            assignment.assigned,
            assignment.accepted,
            assignment.completed,
            assignment.time_to_acceptance,
            assignment.time_to_completion,
        ]
        all_rows.append(row)

    return export_csv(all_rows)


def export_journal_level_citations(journals):
    all_rows = list()
    header_row = [
        'Journal',
        'Total Citations',
    ]
    all_rows.append(header_row)

    for journal in journals:
        all_rows.append(
            [
                journal.name,
                journal.citation_count
            ]
        )

    return export_csv(all_rows)


def export_article_level_citations(articles):
    all_rows = list()
    header_row = [
        'Title',
        'Publication Date',
        'Total Citations',
    ]
    all_rows.append(header_row)

    for article in articles:
        all_rows.append(
            [
                article.title,
                article.date_published,
                article.citation_count,
            ]
        )

    return export_csv(all_rows)


def export_citing_articles(article):
    all_rows = list()
    header_row = [
        'Title',
        'Journal',
        'Year',
        'DOI',
    ]
    all_rows.append(header_row)

    for citing_work in article.articlelink_set.all():
        all_rows.append(
            [
                citing_work.article_title,
                citing_work.journal_title,
                citing_work.year,
                citing_work.doi,
            ]
        )

    return export_csv(all_rows)


def average(lst):
    if lst:
        return round(sum(lst) / len(lst), 2)
    else:
        return 0


def acessses_by_country(journal, start_date, end_date):
    metrics = mm.ArticleAccess.objects.filter(
        article__stage=sm.STAGE_PUBLISHED,
        accessed__gte=start_date,
        accessed__lte=end_date,
    ).values(
        'country__name'
    ).annotate(
        country_count=Count('country')
    )

    if journal:
        metrics = metrics.filter(
            article__journal=journal,
        )

    return metrics


def export_country_csv(metrics):
    all_rows = [['Country', 'Count']]
    for row in metrics:
        all_rows.append(
            [row.get('country__name'), row.get('country_count')]
        )
    return export_csv(all_rows)


@cache(300)
def get_most_viewed_article(metrics):
    from django.db.models import Count

    return metrics.values('article__title').annotate(
        total=Count('article')).order_by('-total')[:1]


@cache(300)
def press_journal_report_data(journals, start_date, end_date):
    data = []

    for journal in journals:
        articles = sm.Article.objects.filter(journal=journal)

        articles_in_journal = articles.filter(
            date_submitted__lte=end_date,
        )

        submissions = articles.exclude(
            stage=sm.STAGE_PUBLISHED,
        ).filter(
            date_submitted__gte=start_date,
            date_submitted__lte=end_date,
        )

        published_articles = articles.filter(
            date_published__gte=start_date,
            date_published__lte=end_date,
        )

        rejected_articles = articles.filter(
            stage=sm.STAGE_REJECTED,
            date_declined__gte=start_date,
            date_declined__lte=end_date,
        )

        metrics = mm.ArticleAccess.objects.filter(
            article__journal=journal,
            accessed__gte=start_date,
            accessed__lte=end_date,
        )

        most_viewed_article = get_most_viewed_article(metrics)

        views = metrics.filter(type='view')
        downloads = metrics.filter(type='download')

        data.append({
            'journal': journal,
            'articles': articles,
            'submitted_articles': articles_in_journal,
            'published_articles': published_articles,
            'submissions': submissions,
            'rejected_articles': rejected_articles,
            'views': views,
            'downloads': downloads,
            'most_viewed_article': most_viewed_article,
            'users': journal.journal_users(),
        })

    return data


def export_press_csv(data_dict):
    all_rows = list()
    header_row = [
        'Journal',
        'Submissions',
        'Published Submissions',
        'Rejected Submissions',
        'Number of Users',
        'Views',
        'Downloads',
        'Most Accessed Article',
    ]
    all_rows.append(header_row)

    for data in data_dict:

        most_viewed_article_string = '{title} ({count})'.format(
            title=data['most_viewed_article'][0]['article__title']  if data['most_viewed_article'] else '',
            count=data['most_viewed_article'][0]['total'] if data['most_viewed_article'] else ''
        )

        row = [
            data.get('journal').name,
            data.get('submissions').count(),
            data.get('published_articles').count(),
            data.get('rejected_articles').count(),
            len(data.get('users')),
            data.get('views').count(),
            data.get('downloads').count(),
            most_viewed_article_string,
        ]
        all_rows.append(row)

    return export_csv(all_rows)


@cache(600)
def journal_usage_by_month_data(date_parts):
    """An attempt to make the view above more performant"""
    journals = jm.Journal.objects.filter(is_remote=False, hide_from_press=False)
    journal_id_map = {j.id: j for j in journals}
    data = {}
    metrics = mm.ArticleAccess.objects.all()


    start = timezone.make_aware(timezone.datetime(
        int(date_parts["start_month_y"]),
        int(date_parts["start_month_m"]),
        1
    ))
    end = timezone.make_aware(timezone.datetime(
        int(date_parts["end_month_y"]),
        int(date_parts["end_month_m"]),
        1
        # get first day of next month at 00:00:00
    ) + relativedelta(months=1))
    

    journal_metrics = metrics.filter(
        article__journal__in=journals,
        type__in=['view', 'download'],
        accessed__gte=start,
        accessed__lt=end,
    ).exclude(
        galley_type__isnull=True,
    ).annotate(
        month=TruncMonth('accessed'),
    ).values(
        # There is no group by in the ORM, this call will translate into:
        # GROUP BY "submission_article"."journal_id",
        #   DATE_TRUNC('month', "metrics_articleaccess"."accessed")
        "article__journal", "month",
    ).annotate(
        # This annotation has to take place after the values above so that it is
        # done over the grouped by clause
        total=Count("id"),
    # This `values` call is turned into the SELECT clause
    ).values("article__journal", "month", "total"
    ).order_by("article__journal", "month")

    dates = [start]
    requested_start = start # preserve original requested start

    while start < end:
        start += relativedelta(months=1)
        if start < end:
            dates.append(start)

    current_journal = None
    maximum = minimum = 0
    for row in journal_metrics:
        journal = journal_id_map[row["article__journal"]]
        data.setdefault(journal, [])
        if journal != current_journal:  # if we have switched to another journal
            # fill gaps if a journal history doesn't have history in the period
            if row["month"] != requested_start:
                delta = relativedelta(row["month"].date(), requested_start.date())
                months_delta = (delta.years * 12) + delta.months
                for _ in range(months_delta):
                    data[journal].append(0)

        month_total = row["total"]
        data[journal].append(month_total)
        if month_total > maximum:
            maximum = month_total
        if month_total < minimum:
            minimum = month_total
        current_journal = journal

    return data, dates, maximum, minimum

@cache(600)
def ajournal_usage_by_month_data(date_parts):
    journals = jm.Journal.objects.filter(is_remote=False, hide_from_press=False)
    data = {}


    start = timezone.datetime(
        int(date_parts["start_month_y"]),
        int(date_parts["start_month_m"]),
        1
    )
    end = timezone.datetime(
        int(date_parts["end_month_y"]),
        # get first day of next month at 00:00:00
        int(date_parts["end_month_m"]) + 1,
        1
    )
    dates = []

    while start < end:
        if start < end:
            # e.g: 2022-01, 2022-02...
            annotation_key = start.strftime("%Y-%m")
            dates.append(annotation_key)
            next_month = start + relativedelta(months=1)

        # Annotate each journal with the metrics for this date range
        journals = journals.annotate(**{
            annotation_key: Subquery(
                build_range_metrics_subq(start, next_month),
                output_field=IntegerField(),
            )
        })
        start = next_month

    for journal in journals:
        # transform the data into tabular format for the template/CSV
        data[journal] = [getattr(journal, date, 0) for date in dates]


    return data, dates

def build_range_metrics_subq(start, end):
    return mm.ArticleAccess.objects.filter(
        article__journal=OuterRef("id"),
        accessed__range=(start, end),
    ).order_by().annotate(
        count=Func(F('id'), function='Count', output_field=IntegerField()),
    ).values('count')


def export_usage_by_month(data, dates):
    all_rows = list()
    header_row = [
        'Journal',
    ]

    for date in dates:
        header_row.append(date)

    all_rows.append(header_row)

    for journal, metrics in data.items():
        row = [
            journal.name,
        ]

        for dm in metrics:
            row.append(dm)

        all_rows.append(row)

    return export_csv(all_rows)


@cache(60)
def peer_review_data(articles, start_date, end_date):
    data = []

    for article in articles:
        reviews = rm.ReviewAssignment.objects.filter(
            article=article,
            date_accepted__isnull=False,
            date_complete__isnull=False,
            date_requested__gte=start_date,
            date_requested__lte=end_date,
        )

        for review in reviews:
            review.request_to_accept = review.date_accepted - review.date_requested
            review.accept_to_complete = review.date_complete - review.date_accepted

        data.append(
            {'article': article, 'reviews': reviews}
        )

    return data


@cache(300)
def peer_review_stats(start_date, end_date, journal=None):
    """Returns peer review statistics for the journal in the given period"""
    submitted_articles = sm.Article.objects.filter(
        date_submitted__gte=start_date,
        date_submitted__lte=end_date,
    )
    if journal:
        submitted_articles = submitted_articles.filter(journal=journal)

    completed_reviews = rm.ReviewAssignment.objects.filter(
        article__in=submitted_articles,
        date_complete__isnull=False,
        date_declined__isnull=True,
    )
    stats = {
        "submitted": submitted_articles.count(),
        "accepted": submitted_articles.filter(date_accepted__isnull=False).count(),
        "rejected": submitted_articles.filter(date_declined__isnull=False).count(),
        "completed_reviews": completed_reviews.count()
    }

    return stats


def export_review_data(data):
    all_rows = list()

    headers = [
        'Reviewer',
        'Journal',
        'Date Requested',
        'Date Accepted',
        'Date Due',
        'Date Complete',
        'Time to Acceptance',
        'Time to Completion',
    ]

    all_rows.append(headers)

    for data_point in data:
        for review in data_point.get('reviews'):
            row = [
                review.reviewer.full_name(),
                strip_tags(data_point.get('article').title),
                review.date_requested,
                review.date_accepted,
                review.date_due,
                review.date_complete,
                review.request_to_accept,
                review.accept_to_complete,
            ]

            all_rows.append(row)

    return export_csv(all_rows)


def current_year():
    return date.today().year


def earliest_citation_year():
    try:
        check = mm.ArticleLink.objects.filter().values_list(
            'pk'
        ).annotate(
            Min('year')
        ).order_by(
            'year'
        )[0]
        return check[1]
    except IndexError:
        return current_year()


def get_year(request):
    return request.GET.get('year', current_year())


@cache(600)
def citation_data(year):
    articles = sm.Article.objects.filter(
        articlelink__year=year,
    )

    return articles


def get_journal_citations(journal):
    counter = 0
    articles = sm.Article.objects.filter(
        articlelink__year__isnull=False,
        journal=journal
    ).distinct()
    for article in articles:
        counter = counter + article.citation_count

    journal.citation_count = counter

    return articles


def write_doi_tsv_report(to_write, journal=None, crosscheck=False):
    """ Writes a TSV of DOI and pointed URLS to the passed object
    :param to_write: An file-like object that can be written to
    :param journal: An optional Journal object to filter the report by
    :param crosscheck: A bool flag for returning URLs to full-text instead
    :return: The Same file-like object passed as an argument
    """
    writer = csv.writer(to_write, delimiter="\t", lineterminator='\n')
    identifiers = id_models.Identifier.objects.filter(
        article__isnull=False,
        article__stage=sm.STAGE_PUBLISHED,
        id_type="doi",
    )

    if journal:
        identifiers = identifiers.filter(article__journal=journal)
    identifiers = identifiers.order_by("article__journal", "id")

    writer.writerow(["DOI", "URL"])
    for identifier in identifiers:
        article = identifier.article
        if crosscheck and article.pdfs.exists():
            path = reverse('serve_article_pdf',
                kwargs={
                    "identifier_type": "id",
                    "identifier": article.id
                }
            )
            url = article.journal.site_url(path)
        else:
            url = article.url
        writer.writerow((identifier.identifier, url))

        # Supplementary file DOIs
        if not crosscheck:
            for supp_file in core_models.SupplementaryFile.objects.filter(
                file__article_id=article.pk,
                doi__isnull=False,
            ):
                writer.writerow((supp_file.doi, supp_file.url()))

    return to_write


def license_report(start, end):
    licenses = []

    articles = sm.Article.objects.filter(
        date_published__lte=end,
        date_published__gte=start,
    ).values('license', 'license__name', 'license__journal__code').annotate(
        lcount=Count('license')
    ).order_by('lcount')

    print(articles)
    return articles
