// Navigation + sitemap configuration (single source for header, section tabs, mobile tab bar, footer and Sitemap).
// Public navigation is task-based: 4 sections, each with a few sub-pages shown as section tabs.
export const SECTIONS = {
  explore: { key: 'explore', home: '/destinations', match: [/^\/destinations/, /^\/festivals/], items: [['Destinations', '/destinations'], ['Festivals & events', '/festivals']] },
  experiences: { key: 'experiences', home: '/experiences', match: [/^\/experiences/], items: [] },
  plan: { key: 'plan', home: '/plan', match: [/^\/plan/], items: [['Itineraries', '/plan'], ['Circuits', '/plan/circuits'], ['Map', '/plan/map'], ['How to reach', '/plan/reach'], ['Official services', '/plan/services'], ['Travel terms', '/dictionary']] },
  verify: { key: 'verify_biz', home: '/verify', match: [/^\/verify/, /^\/directory/], items: [['Verify by reg. no.', '/verify'], ['Directory A-Z', '/directory']] },
  help: { key: 'help', home: '/helplines', match: [/^\/helplines/, /^\/grievance/, /^\/dictionary/, /^\/rules/], items: [['Helplines', '/helplines'], ['File complaint', '/grievance'], ['Track', '/grievance/track'], ['Dictionary', '/dictionary'], ['Rules & licences', '/rules']] },
};
export const MAIN = ['explore', 'experiences', 'plan', 'verify', 'help'];
export const sectionOf = (path) => Object.keys(SECTIONS).find((k) => SECTIONS[k].match.some((re) => re.test(path))) || null;

export const BUSINESS_NAV = [
  ['dashboard', '/business'],
  ['Apply / renew', '/business/apply'],
  ['occupancy', '/business/occupancy'],
  ['api_keys', '/business/api-keys'],
];
export const OFFICER_NAV = [
  ['analytics', '/officer'],
  ['applications', '/officer/applications'],
  ['grievances', '/officer/grievances'],
  ['Advisories', '/officer/advisories'],
  ['events', '/officer/events'],
  ['Businesses', '/officer/businesses'],
];
export const ADMIN_NAV = [['officers', '/officer/officers'], ['Audit log', '/officer/audit']];

export const SITEMAP = [
  ['Explore', [['Home', '/'], ['Search', '/search'], ['Destinations', '/destinations'], ['Festivals & events calendar', '/festivals']]],
  ['Experiences', [['All experiences', '/experiences'], ['Spiritual & Char Dham', '/experiences/spiritual'], ['Adventure & Treks', '/experiences/adventure'],
    ['Wildlife & Nature', '/experiences/wildlife'], ['Yoga & Wellness', '/experiences/wellness'], ['Hill towns & Leisure', '/experiences/leisure'], ['Culture & Fairs', '/experiences/culture']]],
  ['Plan', [['Sample itineraries', '/plan'], ['Circuits', '/plan/circuits'], ['Map (schematic)', '/plan/map'], ['How to reach', '/plan/reach'], ['Official services', '/plan/services']]],
  ['Verify a business', [['Verify by registration number', '/verify'], ['Business directory (A-Z)', '/directory']]],
  ['Help', [['Helplines, alerts & district offices', '/helplines'], ['File a complaint', '/grievance'], ['Track a complaint', '/grievance/track'],
    ['Tourism & hospitality dictionary', '/dictionary'], ['Rules, licences & schemes', '/rules']]],
  ['For businesses (sign in)', [
    ['Business sign in', '/signin?need=business'], ['Create a business account', '/register'], ['Business dashboard', '/business'],
    ['Apply for registration', '/business/apply'], ['Monthly occupancy', '/business/occupancy'], ['API keys for HOI', '/business/api-keys'],
  ]],
  ['For officials (sign in)', [
    ['Officials sign in', '/signin?need=official'], ['Analytics dashboard', '/officer'], ['Applications queue', '/officer/applications'],
    ['Grievance queue', '/officer/grievances'], ['Advisories manager', '/officer/advisories'], ['Events manager', '/officer/events'],
    ['Business registry (officials)', '/officer/businesses'], ['Officer management (state admin)', '/officer/officers'], ['Audit log (state admin)', '/officer/audit'],
  ]],
  ['About this portal', [['About the concept', '/about'], ['Accessibility statement', '/accessibility'], ['Sitemap', '/sitemap']]],
];
