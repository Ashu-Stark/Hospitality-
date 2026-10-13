// Navigation + sitemap configuration (single source for header, section tabs, mobile tab bar, footer and Sitemap).
// Discovery-first information architecture: five top sections a visitor understands at a glance
// (Destinations, Stays, Experiences, Trips, Jobs). "List your property" is a separate call-to-action button for
// businesses; Help (helplines, complaints, dictionary, rules) lives in the utility bar and footer; officials sign in
// from the sign-in menu. Verifying a business sits under Stays, where a visitor decides where to stay.
export const SECTIONS = {
  destinations: { key: 'destinations', home: '/destinations', match: [/^\/destinations/, /^\/plan\/map/], items: [['All destinations', '/destinations'], ['Map', '/plan/map']] },
  stays: { key: 'stays', home: '/stays', match: [/^\/stays/, /^\/verify/, /^\/directory/], items: [['Stays', '/stays'], ['Find a business', '/directory'], ['Check a registration', '/verify']] },
  experiences: { key: 'experiences', home: '/experiences', match: [/^\/experiences/, /^\/festivals/], items: [['With local hosts', '/experiences'], ['By theme', '/experiences/themes'], ['Festivals', '/festivals']] },
  trips: { key: 'trips', home: '/plan', match: [/^\/plan(?!\/map)/], items: [['Trip plans', '/plan'], ['Routes', '/plan/circuits'], ['How to reach', '/plan/reach'], ['Official websites', '/plan/services']] },
  jobs: { key: 'jobs', home: '/jobs', match: [/^\/jobs/], items: [['Find jobs', '/jobs'], ['Hire staff', '/jobs/hire'], ['Staffing agencies', '/jobs/agencies'], ['How it works', '/jobs/about']] },
  help: { key: 'help', home: '/helplines', match: [/^\/helplines/, /^\/grievance/, /^\/dictionary/, /^\/rules/], items: [['Helplines', '/helplines'], ['File complaint', '/grievance'], ['Track', '/grievance/track'], ['Travel words', '/dictionary'], ['Rules & licences', '/rules']] },
  host: { key: 'list_property', home: '/host', match: [/^\/host/], items: [] },
};
export const MAIN = ['destinations', 'stays', 'experiences', 'trips', 'jobs'];
export const sectionOf = (path) => Object.keys(SECTIONS).find((k) => SECTIONS[k].match.some((re) => re.test(path))) || null;

export const BUSINESS_NAV = [
  ['dashboard', '/business'],
  ['Apply / renew', '/business/apply'],
  ['Things to do', '/business/experiences'],
  ['occupancy', '/business/occupancy'],
  ['api_keys', '/business/api-keys'],
  ['hiring', '/business/hiring'],
  ['Staffing agency', '/business/staffing'],
];
export const SEEKER_NAV = [
  ['my_jobsearch', '/seeker'],
  ['my_profile', '/seeker/profile'],
  ['find_jobs', '/jobs'],
];
export const OFFICER_NAV = [
  ['analytics', '/officer'],
  ['applications', '/officer/applications'],
  ['grievances', '/officer/grievances'],
  ['Road alerts', '/officer/advisories'],
  ['events', '/officer/events'],
  ['Businesses', '/officer/businesses'],
];
export const ADMIN_NAV = [['officers', '/officer/officers'], ['Audit log', '/officer/audit']];

export const SITEMAP = [
  ['Destinations', [['Home', '/'], ['Search', '/search'], ['All destinations', '/destinations'], ['Map', '/plan/map']]],
  ['Stays', [['Hotels and homestays', '/stays'], ['Find a business', '/directory'], ['Check a registration number', '/verify']]],
  ['Experiences', [['Things to do with local hosts', '/experiences'], ['Themes', '/experiences/themes'], ['Spiritual & Char Dham', '/experiences/spiritual'], ['Adventure & Treks', '/experiences/adventure'],
    ['Wildlife & Nature', '/experiences/wildlife'], ['Yoga & Wellness', '/experiences/wellness'], ['Hill towns & Leisure', '/experiences/leisure'], ['Culture & Fairs', '/experiences/culture'], ['Festivals', '/festivals']]],
  ['Trips', [['Trip plans', '/plan'], ['Routes', '/plan/circuits'], ['How to reach', '/plan/reach'], ['Official websites', '/plan/services']]],
  ['Jobs', [['Find jobs', '/jobs'], ['Hire staff', '/jobs/hire'], ['Staffing agencies', '/jobs/agencies'], ['How it works & privacy', '/jobs/about'],
    ['Job seeker sign in', '/signin?need=seeker'], ['Create a job-seeker account', '/register?as=seeker'], ['My job search (job seekers)', '/seeker'], ['My profile (job seekers)', '/seeker/profile']]],
  ['List your property / become a host', [['How to join (onboarding steps)', '/host'], ['Create a business account', '/register'], ['Business sign in', '/signin?need=business']]],
  ['Help', [['Helplines and road alerts', '/helplines'], ['Make a complaint', '/grievance'], ['Track a complaint', '/grievance/track'],
    ['Travel words', '/dictionary'], ['Rules and licences', '/rules']]],
  ['For businesses (sign in)', [
    ['Business home', '/business'], ['Register your business', '/business/apply'], ['Things to do you host', '/business/experiences'],
    ['How full you were each month', '/business/occupancy'], ['Connect your hotel software', '/business/api-keys'], ['Hiring', '/business/hiring'],
    ['Post a job', '/business/hiring/new'], ['Find workers', '/business/hiring/candidates'], ['Staffing agency', '/business/staffing'],
  ]],
  ['For officials (sign in)', [
    ['Officials sign in', '/signin?need=official'], ['Numbers at a glance', '/officer'], ['Applications', '/officer/applications'],
    ['Complaints', '/officer/grievances'], ['Jobs and workers', '/officer?tab=jobs'], ['Road alerts', '/officer/advisories'], ['Events', '/officer/events'],
    ['Businesses', '/officer/businesses'], ['Officer management (state admin)', '/officer/officers'], ['Audit log (state admin)', '/officer/audit'],
  ]],
  ['About this site', [['About', '/about'], ['Accessibility statement', '/accessibility'], ['Photo credits', '/credits'], ['Sitemap', '/sitemap']]],
];
