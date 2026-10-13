// English / Hindi labels for navigation and key UI text. Hindi strings are drafts to be reviewed by native speakers.
import { store } from './ui.js';

const STR = {
  en: {
    home: 'Home', destinations: 'Destinations', directory: 'Find a business', festivals: 'Festivals', dictionary: 'Travel words',
    rules: 'Rules & licences', helplines: 'Help & road alerts', grievance: 'Complaint', verify: 'Verify a business',
    search: 'Search', signin: 'Sign in', signout: 'Sign out', dashboard: 'Dashboard', menu: 'Menu', close: 'Close',
    view_public: 'View public site', section: 'Section', officials_area: "Officials' area", business_area: 'Business area',
    sitemap: 'Sitemap', accessibility: 'Accessibility', about: 'About', textsize: 'Text size', skip: 'Skip to main content',
    plan: 'Plan a trip', file: 'File a complaint', track: 'Track a complaint', crowd_now: 'How busy right now', advisories: 'Road alerts',
    upcoming: 'Upcoming festivals', for_business: 'For businesses', for_officials: 'For officials', explore: 'Explore',
    weather: 'Weather', roads: 'Road connectivity', crowd: 'How busy', nearby: 'Nearby verified businesses',
    analytics: 'Numbers', applications: 'Applications', grievances: 'Complaints', events: 'Events', officers: 'Officers',
    my_business: 'My business', apply: 'Apply', occupancy: 'How full', api_keys: 'Connect software', public_site: 'Public',
    search_ph: 'Search places, stays, festivals…', hero_title: 'Find your place in the hills',
    hero_lead: 'Weather, roads, how busy it is, stays, guides and festivals in one place.',
    officials: 'Officials', business: 'Business', all_results: 'See all results',
    explore: 'Explore', experiences: 'Experiences', plan: 'Plan', verify_biz: 'Verify a business', verify_short: 'Verify', help: 'Help', more: 'More',
    business_signin: 'Business sign in', officials_signin: 'Officials sign in', create_account: 'Create business account',
    task_plan: 'Plan a trip', task_check: 'Check a business', task_help: 'Get help or complain', alerts: 'Alerts', coming_up: 'Coming up', see_all: 'See all', credits: 'Photo credits',
    jobs: 'Jobs', task_jobs: 'Find work or hire staff', hiring: 'Hiring', find_jobs: 'Find jobs', my_jobsearch: 'My job search', my_profile: 'My profile',
    seeker_signin: 'Job seeker sign in', job_seeker: 'Job seeker',
    stays: 'Stays', trips: 'Trips', list_property: 'List your property', help_short: 'Help & complaints', local_exp: 'Things to do',
  },
  hi: {
    home: 'मुखपृष्ठ', destinations: 'गंतव्य', directory: 'निर्देशिका', festivals: 'त्योहार', dictionary: 'शब्दकोश',
    rules: 'नियम और लाइसेंस', helplines: 'सहायता और सूचनाएँ', grievance: 'शिकायत', verify: 'व्यवसाय सत्यापित करें',
    search: 'खोजें', signin: 'साइन इन', signout: 'साइन आउट', dashboard: 'डैशबोर्ड', menu: 'मेनू', close: 'बंद करें',
    view_public: 'सार्वजनिक साइट देखें', section: 'अनुभाग', officials_area: 'अधिकारी क्षेत्र', business_area: 'व्यवसाय क्षेत्र',
    sitemap: 'साइटमैप', accessibility: 'सुगम्यता', about: 'परिचय', textsize: 'अक्षर आकार', skip: 'मुख्य सामग्री पर जाएँ',
    plan: 'यात्रा की योजना', file: 'शिकायत दर्ज करें', track: 'शिकायत की स्थिति', crowd_now: 'अभी भीड़', advisories: 'सक्रिय सूचनाएँ',
    upcoming: 'आगामी त्योहार', for_business: 'व्यवसायों के लिए', for_officials: 'अधिकारियों के लिए', explore: 'देखें',
    weather: 'मौसम', roads: 'सड़क संपर्क', crowd: 'भीड़ का स्तर', nearby: 'आसपास के सत्यापित व्यवसाय',
    analytics: 'विश्लेषण', applications: 'आवेदन', grievances: 'शिकायतें', events: 'कार्यक्रम', officers: 'अधिकारी',
    my_business: 'मेरा व्यवसाय', apply: 'आवेदन करें', occupancy: 'अधिभोग', api_keys: 'API कुंजी', public_site: 'सार्वजनिक',
    search_ph: 'गंतव्य, व्यवसाय, त्योहार, शब्द खोजें…', hero_title: 'पहाड़ों में अपनी जगह खोजें',
    hero_lead: 'मौसम, सड़क सूचनाएँ, भीड़ का अनुमान, सत्यापित ठहरने की जगहें, त्योहार और शिकायत: सब एक जगह।',
    officials: 'अधिकारी', business: 'व्यवसाय', all_results: 'सभी परिणाम देखें',
    explore: 'घूमें', experiences: 'अनुभव', plan: 'योजना', verify_biz: 'व्यवसाय सत्यापित करें', verify_short: 'सत्यापन', help: 'सहायता', more: 'और',
    business_signin: 'व्यवसाय साइन इन', officials_signin: 'अधिकारी साइन इन', create_account: 'व्यवसाय खाता बनाएँ',
    task_plan: 'यात्रा की योजना', task_check: 'व्यवसाय जाँचें', task_help: 'सहायता या शिकायत', alerts: 'सूचनाएँ', coming_up: 'आगामी', see_all: 'सभी देखें', credits: 'फ़ोटो श्रेय',
    jobs: 'नौकरियाँ', task_jobs: 'काम खोजें या स्टाफ रखें', hiring: 'भर्ती', find_jobs: 'नौकरी खोजें', my_jobsearch: 'मेरी नौकरी खोज', my_profile: 'मेरी प्रोफ़ाइल',
    seeker_signin: 'नौकरी खोजने वाले साइन इन', job_seeker: 'नौकरी खोजने वाले',
    stays: 'ठहरने की जगहें', trips: 'यात्राएँ', list_property: 'अपनी संपत्ति जोड़ें', help_short: 'सहायता और शिकायत', local_exp: 'स्थानीय अनुभव',
  },
};

let lang = store('uthp.lang') === 'hi' ? 'hi' : 'en';
export const getLang = () => lang;
export function setLang(l) {
  lang = l === 'hi' ? 'hi' : 'en';
  store('uthp.lang', lang);
  document.documentElement.lang = lang;
}
export const t = (k) => STR[lang][k] ?? STR.en[k] ?? k;
document.documentElement.lang = lang;
