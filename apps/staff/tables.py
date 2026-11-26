"""Small helpers for sortable, filterable, paginated admin tables."""

from django.core.paginator import Paginator

PAGE_SIZES = (25, 50, 100)


class Table:
    """Holds sort state for a queryset.

    columns: {"key": "orm_field"}; ?sort=key&dir=asc|desc picks the ordering.
    """

    def __init__(self, request, queryset, columns, default="-created", per_page=25):
        self.request = request
        self.columns = columns
        sort = request.GET.get("sort", default.lstrip("-"))
        direction = request.GET.get("dir", "desc" if default.startswith("-") else "asc")
        if sort not in columns:
            sort, direction = default.lstrip("-"), "desc" if default.startswith("-") else "asc"
        self.sort, self.dir = sort, ("desc" if direction == "desc" else "asc")
        field = columns[sort]
        order = f"-{field}" if self.dir == "desc" else field
        self.queryset = queryset.order_by(order, "-pk")
        try:
            size = int(request.GET.get("per_page", per_page))
        except ValueError:
            size = per_page
        self.per_page = size if size in PAGE_SIZES else per_page
        self.page = Paginator(self.queryset, self.per_page).get_page(request.GET.get("page"))

    def querystring(self, **overrides):
        q = self.request.GET.copy()
        for k, v in overrides.items():
            if v is None:
                q.pop(k, None)
            else:
                q[k] = v
        return q.urlencode()

    def header(self, key):
        """(url_query, aria_sort, arrow) for a sortable column header."""
        if key == self.sort:
            nxt = "asc" if self.dir == "desc" else "desc"
            aria = "descending" if self.dir == "desc" else "ascending"
            arrow = "↓" if self.dir == "desc" else "↑"
        else:
            nxt, aria, arrow = "asc", "none", ""
        return self.querystring(sort=key, dir=nxt, page=None), aria, arrow
