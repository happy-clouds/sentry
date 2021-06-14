import {Component} from 'react';
import {browserHistory, WithRouterProps} from 'react-router';
import {Location} from 'history';

import Feature from 'app/components/acl/feature';
import Alert from 'app/components/alert';
import LightWeightNoProjectMessage from 'app/components/lightWeightNoProjectMessage';
import GlobalSelectionHeader from 'app/components/organizations/globalSelectionHeader';
import SentryDocumentTitle from 'app/components/sentryDocumentTitle';
import {t} from 'app/locale';
import {GlobalSelection, Organization, Project} from 'app/types';
import EventView from 'app/utils/discover/eventView';
import {
  isAggregateField,
  SPAN_OP_BREAKDOWN_FIELDS,
  SPAN_OP_RELATIVE_BREAKDOWN_FIELD,
} from 'app/utils/discover/fields';
import {decodeScalar} from 'app/utils/queryString';
import {stringifyQueryObject, tokenizeSearch} from 'app/utils/tokenizeSearch';
import withGlobalSelection from 'app/utils/withGlobalSelection';
import withOrganization from 'app/utils/withOrganization';
import withProjects from 'app/utils/withProjects';

import {getTransactionName} from '../../utils';

import EventsPageContent from './content';

type Props = {
  location: Location;
  organization: Organization;
  projects: Project[];
  selection: GlobalSelection;
} & Pick<WithRouterProps, 'router'>;

type State = {
  eventView: EventView | undefined;
};

class TransactionEvents extends Component<Props, State> {
  state: State = {
    eventView: generateEventsEventView(
      this.props.location,
      getTransactionName(this.props.location)
    ),
  };

  static getDerivedStateFromProps(nextProps: Readonly<Props>, prevState: State): State {
    return {
      ...prevState,
      eventView: generateEventsEventView(
        nextProps.location,
        getTransactionName(nextProps.location)
      ),
    };
  }

  getDocumentTitle(): string {
    const name = getTransactionName(this.props.location);

    const hasTransactionName = typeof name === 'string' && String(name).trim().length > 0;

    if (hasTransactionName) {
      return [String(name).trim(), t('Events')].join(' \u2014 ');
    }

    return [t('Summary'), t('Events')].join(' \u2014 ');
  }

  renderNoAccess = () => {
    return <Alert type="warning">{t("You don't have access to this feature")}</Alert>;
  };

  render() {
    const {organization, projects, location} = this.props;
    const {eventView} = this.state;
    const transactionName = getTransactionName(location);
    if (!eventView || transactionName === undefined) {
      // If there is no transaction name, redirect to the Performance landing page
      browserHistory.replace({
        pathname: `/organizations/${organization.slug}/performance/`,
        query: {
          ...location.query,
        },
      });
      return null;
    }

    const shouldForceProject = eventView.project.length === 1;
    const forceProject = shouldForceProject
      ? projects.find(p => parseInt(p.id, 10) === eventView.project[0])
      : undefined;
    const projectSlugs = eventView.project
      .map(projectId => projects.find(p => parseInt(p.id, 10) === projectId))
      .filter((p: Project | undefined): p is Project => p !== undefined)
      .map(p => p.slug);
    return (
      <SentryDocumentTitle
        title={this.getDocumentTitle()}
        orgSlug={organization.slug}
        projectSlug={forceProject?.slug}
      >
        <Feature
          features={['performance-events-page']}
          organization={organization}
          renderDisabled={this.renderNoAccess}
        >
          <GlobalSelectionHeader
            lockedMessageSubject={t('transaction')}
            shouldForceProject={shouldForceProject}
            forceProject={forceProject}
            specificProjectSlugs={projectSlugs}
            disableMultipleProjectSelection
            showProjectSettingsLink
          >
            <LightWeightNoProjectMessage organization={organization}>
              <EventsPageContent
                location={location}
                eventView={eventView}
                transactionName={transactionName}
                organization={organization}
                projects={projects}
              />
            </LightWeightNoProjectMessage>
          </GlobalSelectionHeader>
        </Feature>
      </SentryDocumentTitle>
    );
  }
}

function generateEventsEventView(
  location: Location,
  transactionName: string | undefined
): EventView | undefined {
  if (transactionName === undefined) {
    return undefined;
  }
  // Use the user supplied query but overwrite any transaction or event type
  // conditions they applied.
  const query = decodeScalar(location.query.query, '');
  const conditions = tokenizeSearch(query);
  conditions
    .setTagValues('event.type', ['transaction'])
    .setTagValues('transaction', [transactionName]);

  Object.keys(conditions.tagValues).forEach(field => {
    if (isAggregateField(field)) conditions.removeTag(field);
  });

  // Default fields for relative span view
  const fields = [
    'id',
    'user.display',
    SPAN_OP_RELATIVE_BREAKDOWN_FIELD,
    'transaction.duration',
    'trace',
    'timestamp',
    'spans.total.time',
  ];
  fields.push(...SPAN_OP_BREAKDOWN_FIELDS);

  return EventView.fromNewQueryWithLocation(
    {
      id: undefined,
      version: 2,
      name: transactionName,
      fields,
      query: stringifyQueryObject(conditions),
      projects: [],
      orderby: '-timestamp',
    },
    location
  );
}

export default withGlobalSelection(withProjects(withOrganization(TransactionEvents)));
