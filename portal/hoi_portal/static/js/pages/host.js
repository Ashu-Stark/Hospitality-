// "List your property / become a host": a friendly partner-onboarding entry for every kind of tourism business.
// It explains who can join, what each gets, and the four steps (account -> application -> officer review -> live),
// then hands over to the existing register / apply flow with the business type pre-selected.
import { html, mount, load, $, href, mediaCard, details, table, lastUpdated } from '../ui.js';
import { meta, user } from '../api.js';
import { cover, photo, credit } from '../photos.js';

const PARTNERS = [
  {
    type: 'homestay', photo: ['lx-farm_stay', 'lx-village_walk', 'munsiyari'], kicker: 'Homestays and hotels', title: 'List your stay',
    ticks: ['Shown on Stays with your registration number and Verified badge', 'Share how full you are once a month, or automatically', 'Link your stay to local experiences nearby'],
  },
  {
    type: 'guide', photo: ['lx-nature_walk', 'lx-birding', 'chopta'], kicker: 'Guides and adventure operators', title: 'Host local experiences',
    ticks: ['List village walks, nature walks, birding or workshops', 'Visitors send a request to join; you confirm directly', 'No commission or payment on this portal'],
  },
  {
    type: 'staffing_agency', photo: ['lx-artisan_workshop', 'dehradun'], kicker: 'Staffing agencies', title: 'Supply staff in peak season',
    ticks: ['Offer a team: “12 housekeeping staff, Apr–Jun”', 'Get a message when a hotel is short of staff', 'Respond with how many workers you can send'],
  },
  {
    type: 'transport', photo: ['lx-heritage_walk', 'rishikesh'], kicker: 'Taxis, restaurants, agents, tour operators', title: 'Get registered and verified',
    ticks: ['One application for every business type', 'Visitors can check your registration number', 'Post jobs and find local staff on the hiring board'],
  },
];
const STEPS = [
  ['Create an account', 'Username and password. Takes a minute.'],
  ['Apply', 'Tell us your business type, district and size. Tick the papers you have.'],
  ['We check it', 'The district tourism office says yes, or asks you to fix something.'],
  ['You are live', 'You get a registration number. Then add things to do, post jobs or offer staff.'],
];

export async function page(ctx) {
  const el = ctx.el;
  const u = user();
  const isBiz = u?.role === 'business';
  const start = (type) => (isBiz ? href('/business/apply', { type }) : href('/register', { next: '/business/apply?type=' + type }));
  const hp = photo('lx-village_walk') || photo('hero');
  mount(el, html`<section class="photohero" aria-labelledby="hh">${hp ? html`${cover(['lx-village_walk', 'hero'], { eager: true })}` : ''}
      <div class="ph-in"><p class="eyebrow">For tourism businesses</p><h1 id="hh">List your property, host experiences, hire staff</h1>
        <p>One sign-up for homestays, hotels, guides, staffing agencies and every other travel business. It is free.</p>
        <div class="btnrow section">${isBiz ? html`<a class="btn primary" href="#/business">Go to your dashboard</a><a class="btn" href="#/business/apply">Apply for a registration</a>`
          : html`<a class="btn primary" href="${href('/register', { next: '/business/apply' })}">Start: create a business account</a><a class="btn" href="#/signin?need=business">I already have an account</a>`}</div></div>
      ${hp ? credit(hp) : ''}</section>
    <section class="sec2" aria-labelledby="who-h"><div class="sechead"><h2 id="who-h">Who can join</h2></div>
      <div class="mcgrid g4c partner-grid">${PARTNERS.map((p) => mediaCard({
        href: start(p.type), media: cover(p.photo, { seed: p.type }), kicker: p.kicker, kickerIcon: p.type, title: p.title,
        foot: html`<ul class="ticks">${p.ticks.map((t) => html`<li>${t}</li>`)}</ul>`,
      }))}</div></section>
    <section class="sec2" aria-labelledby="st-h"><div class="sechead"><h2 id="st-h">Four steps</h2><p class="sub">Most of it is done from your business dashboard.</p></div>
      <ol class="steps">${STEPS.map(([b, s]) => html`<li><b>${b}</b><span>${s}</span></li>`)}</ol></section>
    <div id="docs" class="sec2"></div>
    ${lastUpdated(null)}`);
  await load($('#docs', el), async () => {
    const m = await meta();
    const label = Object.fromEntries(m.documents_checklist.map((d) => [d.key, d.label]));
    mount($('#docs', el), details('Papers to keep ready', table([{ key: 'type', label: 'Business type' }, { key: 'docs', label: 'Papers to keep ready' }],
      m.business_types.map((b) => ({ type: b.label, docs: (m.required_documents[b.key] || []).map((k) => label[k]).join('; ') })), 'Documents checklist by business type')));
  }, { skel: 'block' });
}
