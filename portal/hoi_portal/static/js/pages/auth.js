// Sign in (officials + business, one-click demo accounts when the API offers them) and business registration.
import { html, mount, $, $$, field, showErrors, clearErrors, apiFieldErrors, busy, crumbs, errorBox, toast } from '../ui.js';
import { login, register as registerApi, demoLogin, demoAccounts, user } from '../api.js';
import { go } from '../router.js';
import { t } from '../i18n.js';

function after(u, next) {
  const home = u.role === 'business' ? '/business' : '/officer';
  if (next && next.startsWith('/') && !next.startsWith('//')) {
    const okBiz = next.startsWith('/business');
    const okOff = next.startsWith('/officer');
    if ((okBiz && u.role === 'business') || (okOff && u.role !== 'business') || (!okBiz && !okOff)) {
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
  const title = need === 'business' ? 'Business sign in' : need === 'official' ? 'Officials sign in' : 'Sign in';
  mount(el, html`${crumbs([['Home', '#/'], [title]])}
    <div class="pagehead"><div><p class="eyebrow">${need === 'business' ? t('for_business') : need === 'official' ? t('for_officials') : 'Businesses and officials'}</p><h1>${title}</h1>
      <p>Visitors do not need an account. Sign in to manage a business registration, or as a district officer or state admin.</p></div></div>
    ${u ? html`<p class="flag blue">You are signed in as <strong>${u.username}</strong> (${u.role_label}). <a href="#${u.role === 'business' ? '/business' : '/officer'}">Go to your dashboard</a>.</p>` : ''}
    ${next ? html`<p class="flag amber" role="status">Please sign in${need === 'business' ? ' with a business account' : need === 'official' ? ' with an official account' : ''} to open that page.</p>` : ''}
    <div class="split">
      <form class="card form" id="lf" novalidate><h2>Username and password</h2>
        ${field({ id: 'username', label: 'Username', required: true, attrs: 'autocomplete="username" maxlength="60" autocapitalize="off" spellcheck="false"' })}
        ${field({ id: 'password', label: 'Password', type: 'password', required: true, attrs: 'autocomplete="current-password" maxlength="200"' })}
        <div class="btnrow"><button class="btn primary" type="submit">${t('signin')}</button><a href="#/register">Create a business account</a></div>
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
  const order = need === 'business' ? ['business', 'district_officer', 'state_admin'] : ['district_officer', 'state_admin', 'business'];
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
  mount(el, html`${crumbs([['Home', '#/'], ['Create a business account']])}
    <div class="pagehead"><div><p class="eyebrow">${t('for_business')}</p><h1>Create a business account</h1>
      <p>For owners and operators of hotels, homestays, guide services, travel agencies, transport and adventure businesses. After creating the account you can apply for registration.</p></div></div>
    <form class="card form narrow" id="rf" novalidate>
      ${field({ id: 'username', label: 'Choose a username', required: true, hint: '3-40 characters: letters, digits, dot, dash or underscore.', attrs: 'autocomplete="username" maxlength="40" autocapitalize="off" spellcheck="false"' })}
      ${field({ id: 'password', label: 'Password', type: 'password', required: true, hint: 'At least 10 characters. Use a passphrase you do not use elsewhere.', attrs: 'autocomplete="new-password" maxlength="200"' })}
      ${field({ id: 'password2', label: 'Repeat password', type: 'password', required: true, attrs: 'autocomplete="new-password" maxlength="200"' })}
      <div class="btnrow"><button class="btn primary" type="submit">Create account</button><a href="#/signin?need=business">I already have an account</a></div>
    </form><div id="rres" aria-live="polite"></div>`);
  const form = $('#rf', el);
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
      await registerApi(username, password);
      toast('Account created. Next: apply for registration.');
      go('/business/apply');
    } catch (err) {
      busy(btn, false);
      if (err.status === 409) showErrors(form, { username: err.message });
      else if (err.status === 422) showErrors(form, apiFieldErrors(err), err.message);
      else mount($('#rres', el), errorBox(err, { retry: false }));
    }
  });
}
