from django.utils.functional import cached_property
from parsimonious.exceptions import IncompleteParseError

from sentry.api.event_search import (
    AggregateFilter,
    SearchFilter,
    SearchKey,
    SearchValue,
    SearchVisitor,
    event_search_grammar,
    is_negated,
)
from sentry.exceptions import InvalidSearchQuery
from sentry.models.group import STATUS_QUERY_CHOICES
from sentry.search.events.constants import EQUALITY_OPERATORS
from sentry.search.events.filter import to_list
from sentry.search.utils import (
    parse_actor_or_none_value,
    parse_release,
    parse_status_value,
    parse_user_value,
)
from sentry.utils.compat import map


class IssueSearchVisitor(SearchVisitor):
    key_mappings = {
        "assigned_to": ["assigned"],
        "bookmarked_by": ["bookmarks"],
        "subscribed_by": ["subscribed"],
        "assigned_or_suggested": ["assigned_or_suggested"],
        "first_release": ["first-release", "firstRelease"],
        "first_seen": ["age", "firstSeen"],
        "last_seen": ["lastSeen"],
        "active_at": ["activeSince"],
        # TODO: Special case this in the backends, since they currently rely
        # on date_from and date_to explicitly
        "date": ["event.timestamp"],
        "times_seen": ["timesSeen"],
        "sentry:dist": ["dist"],
    }
    numeric_keys = SearchVisitor.numeric_keys.union(["times_seen"])
    date_keys = SearchVisitor.date_keys.union(["active_at", "date"])

    @cached_property
    def is_filter_translators(self):
        is_filter_translators = {
            "assigned": (SearchKey("unassigned"), SearchValue(False)),
            "unassigned": (SearchKey("unassigned"), SearchValue(True)),
            "for_review": (SearchKey("for_review"), SearchValue(True)),
            "linked": (SearchKey("linked"), SearchValue(True)),
            "unlinked": (SearchKey("linked"), SearchValue(False)),
        }
        for status_key, status_value in STATUS_QUERY_CHOICES.items():
            is_filter_translators[status_key] = (SearchKey("status"), SearchValue(status_value))
        return is_filter_translators

    def visit_is_filter(self, node, children):
        # the key is "is" here, which we don't need
        negation, _, _, _, search_value = children

        if search_value.raw_value.startswith("["):
            raise InvalidSearchQuery('"in" syntax invalid for "is" search')

        if search_value.raw_value not in self.is_filter_translators:
            raise InvalidSearchQuery(
                'Invalid value for "is" search, valid values are {}'.format(
                    sorted(self.is_filter_translators.keys())
                )
            )

        search_key, search_value = self.is_filter_translators[search_value.raw_value]

        operator = "!=" if is_negated(negation) else "="

        return SearchFilter(search_key, operator, search_value)

    def visit_boolean_operator(self, node, children):
        raise InvalidSearchQuery(
            'Boolean statements containing "OR" or "AND" are not supported in this search'
        )


def parse_search_query(query):
    try:
        tree = event_search_grammar.parse(query)
    except IncompleteParseError as e:
        raise InvalidSearchQuery(
            "%s %s"
            % (
                "Parse error: %r (column %d)." % (e.expr.name, e.column()),
                "This is commonly caused by unmatched-parentheses. Enclose any text in double quotes.",
            )
        )
    return IssueSearchVisitor(allow_boolean=False).visit(tree)


def convert_actor_or_none_value(value, projects, user, environments):
    # TODO: This will make N queries. This should be ok, we don't typically have large
    # lists of actors here, but we can look into batching it if needed.
    return [parse_actor_or_none_value(projects, actor, user) for actor in value]


def convert_user_value(value, projects, user, environments):
    # TODO: This will make N queries. This should be ok, we don't typically have large
    # lists of usernames here, but we can look into batching it if needed.
    return [parse_user_value(username, user) for username in value]


def convert_release_value(value, projects, user, environments):
    # TODO: This will make N queries. This should be ok, we don't typically have large
    # lists of versions here, but we can look into batching it if needed.
    return [parse_release(version, projects, environments) for version in value]


def convert_status_value(value, projects, user, environments):
    parsed = []
    for status in value:
        try:
            parsed.append(parse_status_value(status))
        except ValueError:
            raise InvalidSearchQuery(f"invalid status value of '{status}'")
    return parsed


value_converters = {
    "assigned_or_suggested": convert_actor_or_none_value,
    "assigned_to": convert_actor_or_none_value,
    "bookmarked_by": convert_user_value,
    "subscribed_by": convert_user_value,
    "first_release": convert_release_value,
    "release": convert_release_value,
    "status": convert_status_value,
}


def convert_query_values(search_filters, projects, user, environments):
    """
    Accepts a collection of SearchFilter objects and converts their values into
    a specific format, based on converters specified in `value_converters`.
    :param search_filters: Collection of `SearchFilter` objects.
    :param projects: List of projects being searched across
    :param user: The user making the search
    :return: New collection of `SearchFilters`, which may have converted values.
    """

    def convert_search_filter(search_filter):
        if search_filter.key.name in value_converters:
            converter = value_converters[search_filter.key.name]
            new_value = converter(
                to_list(search_filter.value.raw_value), projects, user, environments
            )
            search_filter = search_filter._replace(
                value=SearchValue(new_value),
                operator="IN" if search_filter.operator in EQUALITY_OPERATORS else "NOT IN",
            )
        elif isinstance(search_filter, AggregateFilter):
            raise InvalidSearchQuery(
                f"Aggregate filters ({search_filter.key.name}) are not supported in issue searches."
            )
        return search_filter

    return map(convert_search_filter, search_filters)
