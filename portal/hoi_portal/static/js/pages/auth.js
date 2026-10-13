// Sign in (officials + business, one-click demo accounts when the API offers them) and business registration.
import { html, mount, $, $$, raw, href, field, showErrors, clearErrors, apiFieldErrors, busy, crumbs, errorBox, toast } from '../ui.js';
import { login, register as registerApi, demoLogin, demoAccounts, user, homeOf } from '../api.js';
import { go } from '../router.js';
import { t } from '../i18n.js';

function after(u, next) {
  const home = homeOf(u.role);
  if (next && next.startsWith('/') && !next.startsWith('//')) {
    const okBiz = next.startsWith('/business');
    const okOff = next.startsWith('/officer');
    const okSeek = next.startsWith('/seeker');
    const official = !['business', 'job_seeker'].includes(u.role);
    if ((okBiz && u.role === 'business') || (okOff && official) || (okSeek && u.role === 'job_seeker') || (!okBiz && !okOff && !okSeek)) {
      location.hash = next;
      return;
    }
  }
  go(home);
}

export async function signin(ctx) {
  const el = ctx.el;
  const need = ctx.query.need;
  const next = ctx.query.next;
  const u = user();
  const title = need === 'business' ? 'Business sign in' : need === 'official' ? 'Officials sign in' : need === 'seeker' ? 'Job seeker sign in' : 'Sign in';
  mount(el, html`${crumbs([['Home', '#/'], [title]])}
    <div class="pagehead"><div><img class="authmark" src="img/brand/hoi-mark.svg" alt="" width="56" height="56"><p class="eyebrow">${need === 'business' ? t('for_business') : need === 'official' ? t('for_officials') : need === 'seeker' ? t('jobs') : 'Businesses, job seekers and officials'}</p><h1>${title}</h1>
      <p>${need === 'seeker' ? 'Sign in to manage your job-seeker profile, applications and employer requests.' : 'Visitors do not need an account. Sign in to manage a business registration, as a job seeker, or as a district officer or state admin.'}</p></div></div>
    ${u ? html`<p class="flag blue">You are signed in as <strong>${u.username}</strong> (${u.role_label}). <a href="#${homeOf(u.role)}">Go to your dashboard</a>.</p>` : ''}
    ${next ? html`<p class="flag amber" role="status">Please sign in${need === 'business' ? ' with a business account' : need === 'official' ? ' with an official account' : ''} to open that page.</p>` : ''}
    <div class="split">
      <form class="card form" id="lf" novalidate><h2>Username and password</h2>
        ${field({ id: 'username', label: 'Username', required: true, attrs: 'autocomplete="username" maxlength="60" autocapitalize="off" spellcheck="false"' })}
        ${field({ id: 'password', label: 'Password', type: 'password', required: true, attrs: 'autocomplete="current-password" maxlength="200"' })}
        <div class="btnrow"><button class="btn primary" type="submit">${t('signin')}</button><a href="${need === 'seeker' ? '#/register?as=seeker' : '#/register'}">${need === 'seeker' ? 'Create a job-seeker account' : 'Create an account'}</a></div>
        <p class="hint section">Officer accounts are created by the state admin.</p>
      </form>
      <section class="card" aria-labelledby="demo-h"><h2 id="demo-h">Demo accounts</h2><p class="small muted">One click, for the hackathon demo only. Disabled on a production server.</p><div id="demo" class="section"></div></section>
    </div><div id="lres" aria-live="polite"></div>`);
  const form = $('#lf', el);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const username = (fd.get('username') || '').toString().trim();
    const password = (fd.get('password') || '').toString();
    const errs = {};
    if (!username) errs.username = 'Enter your username.';
    if (!password) errs.password = 'Enter your password.';
    if (Object.keys(errs).length) { showErrors(form, errs); return; }
    clearErrors(form);
    const btn = form.querySelector('button[type=submit]');
    busy(btn, true, 'Signing in…');
    try {
      const nu = await login(username, password);
      toast(`Signed in as ${nu.username}`);
      after(nu, next);
    } catch (err) {
      busy(btn, false);
      if (err.status === 401 || err.status === 422) showErrors(form, {}, err.status === 401 ? 'Username or password is not correct.' : err.message);
      else mount($('#lres', el), errorBox(err, { retry: false }));
    }
  });
  const demos = await demoAccounts();
  const box = $('#demo', el);
  if (!demos.length) { mount(box, html`<p class="muted">Demo sign-in is turned off on this server.</p>`); return; }
  const order = need === 'business' ? ['business', 'job_seeker', 'district_officer', 'state_admin'] : need === 'seeker' ? ['job_seeker', 'business', 'district_officer', 'state_admin'] : ['district_officer', 'state_admin', 'business', 'job_seeker'];
  demos.sort((a, b) => order.indexOf(a.role) - order.indexOf(b.role));
  mount(box, html`<div class="demo">${demos.map((d) => html`<button type="button" data-demo="${d.username}"><b>${d.label}</b><span>${d.description}</span><span class="mono">${d.username}</span></button>`)}</div>`);
  $$('[data-demo]', box).forEach((b) => b.addEventListener('click', async () => {
    b.disabled = true;
    b.setAttribute('aria-busy', 'true');
    try {
      const nu = await demoLogin(b.dataset.demo);
      toast(`Signed in as ${nu.label || nu.username}`);
      after(nu, next);
    } catch (err) {
      b.disabled = false;
      b.removeAttribute('aria-busy');
      mount($('#lres', el), errorBox(err, { retry: false }));
    }
  }));
}

export async function register(ctx) {
  const el = ctx.el;
  let as = ctx.query.as === 'seeker' ? 'job_seeker' : 'business';
  const next = ctx.query.next;
  mount(el, html`${crumbs([['Home', '#/'], ['Create an account']])}
    <div class="pagehead"><div><img class="authmark" src="img/brand/hoi-mark.svg" alt="" width="56" height="56"><p class="eyebrow" id="rg-eb"></p><h1 id="rg-h"></h1><p id="rg-p"></p></div></div>
    <form class="card form narrow" id="rf" novalidate>
      <fieldset class="fld"><legend class="lbl">Account type</legend><div class="chips">
        <label class="check"><input type="radio" name="role" value="job_seeker" ${as === 'job_seeker' ? raw('checked') : ''}>I am looking for work</label>
        <label class="check"><input type="radio" name="role" value="business" ${as === 'business' ? raw('checked') : ''}>I run a tourism business</label></div></fieldset>
      ${field({ id: 'username', label: 'Choose a username', required: true, hint: '3-40 characters: letters, digits, dot, dash or underscore. It is not shown to employers.', attrs: 'autocomplete="username" maxlength="40" autocapitalize="off" spellcheck="false"' })}
      ${field({ id: 'password', label: 'Password', type: 'password', required: true, hint: 'At least 10 characters. Use a passphrase you do not use elsewhere.', attrs: 'autocomplete="new-password" maxlength="200"' })}
      ${field({ id: 'password2', label: 'Repeat password', type: 'password', required: true, attrs: 'autocomplete="new-password" maxlength="200"' })}
      <div class="btnrow"><button class="btn primary" type="submit">Create account</button><a id="rg-in" href="#/signin">I already have an account</a></div>
    </form><div id="rres" aria-live="polite"></div>`);
  const text = () => {
    const seek = as === 'job_seeker';
    $('#rg-eb', el).textContent = seek ? t('jobs') : t('for_business');
    $('#rg-h', el).textContent = seek ? 'Create a job-seeker account' : 'Create a business account';
    $('#rg-p', el).textContent = seek
      ? 'Free. Next you build a short profile with your skills; employers never see your phone or email unless you accept their request.'
      : 'For owners and operators of hotels, homestays, guide services, travel agencies, transport and adventure businesses. After creating the account you can apply for registration.';
    $('#rg-in', el).setAttribute('href', href('/signin', { need: seek ? 'seeker' : 'business', next }));
  };
  text();
  const form = $('#rf', el);
  form.addEventListener('change', (e) => { if (e.target.name === 'role') { as = e.target.value; text(); } });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const username = (fd.get('username') || '').toString().trim();
    const password = (fd.get('password') || '').toString();
    const errs = {};
    if (!/^[A-Za-z0-9._-]{3,40}$/.test(username)) errs.username = 'Use 3-40 letters, digits, dot, dash or underscore.';
    if (password.length < 10) errs.password = 'Use at least 10 characters.';
    else if (password !== fd.get('password2')) errs.password2 = 'The passwords do not match.';
    if (Object.keys(errs).length) { showErrors(form, errs); return; }
    clearErrors(form);
    const btn = form.querySelector('button[type=submit]');
    busy(btn, true, 'Creating…');
    try {
      await registerApi(username, password, as);
      if (as === 'job_seeker') { toast('Account created. Next: your profile.'); go('/seeker/profile', next ? { next } : undefined); }
      else { toast('Account created. Next: apply for registration.'); go('/business/apply'); }
    } catch (err) {
      busy(btn, false);
      if (err.status === 409) showErrors(form, { username: err.message });
      else if (err.status === 422) showErrors(form, apiFieldErrors(err), err.message);
      else mount($('#rres', el), errorBox(err, { retry: false }));
    }
  });
}
