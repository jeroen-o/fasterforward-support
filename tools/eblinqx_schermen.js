/* Schermafbeeldingen maken in de demo-omgeving van eBlinqx Connect (alleen fictieve gegevens!).
 *
 * Inloggegevens komen uit omgevingsvariabelen, nooit uit de code of de chat:
 *   EBLINQX_URL         (standaard: de inloglink van de demo-omgeving)
 *   EBLINQX_GEBRUIKER, EBLINQX_WACHTWOORD
 *   EBLINQX_TOTP        optioneel: geheime sleutel van de authenticator-app (base32)
 *   EBLINQX_CODE        optioneel: eenmalige verificatiecode (als er geen TOTP-sleutel is)
 *
 * Gebruik:
 *   node tools/eblinqx_schermen.js inloggen            # inloggen en sessie bewaren in tools/.eblinqx-sessie.json
 *   node tools/eblinqx_schermen.js scherm <pad> <uitvoer.png> [css-selector-om-te-markeren]
 *
 * De sessie wordt bewaard buiten git (.gitignore), zodat verificatie maar één keer nodig is.
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const INLOG = process.env.EBLINQX_URL || 'https://demo-omgeving.vh.eblinqx.tech/?data=rvmKMOm%2FhSfLionl2R19QBhSSmI1vSfPeKGR%2FpXSIYYMA%2FigHw%3D%3D';
const BASIS = new URL(INLOG).origin;
const SESSIE = path.join(__dirname, '.eblinqx-sessie.json');

function totp(secret) {
  const alfabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const c of secret.replace(/[\s=]/g, '').toUpperCase()) bits += alfabet.indexOf(c).toString(2).padStart(5, '0');
  const key = Buffer.from(bits.match(/.{8}/g).map(b => parseInt(b, 2)));
  const t = Buffer.alloc(8); t.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const h = crypto.createHmac('sha1', key).update(t).digest();
  const o = h[h.length - 1] & 15;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1000000).padStart(6, '0');
}

async function inloggen() {
  const g = process.env.EBLINQX_GEBRUIKER, w = process.env.EBLINQX_WACHTWOORD;
  if (!g || !w) throw new Error('EBLINQX_GEBRUIKER en EBLINQX_WACHTWOORD ontbreken (zet ze als omgevingsgeheim).');
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, locale: 'nl-NL' });
  const p = await ctx.newPage();
  await p.goto(INLOG, { waitUntil: 'domcontentloaded' });
  await p.fill('#frmTxtUsername', g);
  await p.fill('#frmTxtPassword', w);
  await Promise.all([p.waitForLoadState('domcontentloaded'), p.press('#frmTxtPassword', 'Enter')]);
  await p.waitForTimeout(2500);
  // tweestapsverificatie: veld met een code
  const codeVeld = await p.$('input[autocomplete="one-time-code"], input[name*="code" i], input[id*="code" i], input[name*="token" i]');
  if (codeVeld) {
    const code = process.env.EBLINQX_TOTP ? totp(process.env.EBLINQX_TOTP) : process.env.EBLINQX_CODE;
    if (!code) { await p.screenshot({ path: path.join(__dirname, '.eblinqx-2fa.png') }); throw new Error('Verificatiecode nodig: zet EBLINQX_CODE (eenmalig) of EBLINQX_TOTP.'); }
    await codeVeld.fill(code);
    await Promise.all([p.waitForLoadState('domcontentloaded'), codeVeld.press('Enter')]);
    await p.waitForTimeout(2500);
  }
  if (await p.$('#frmTxtPassword')) throw new Error('Inloggen mislukt (nog steeds op het inlogscherm).');
  await ctx.storageState({ path: SESSIE });
  console.log('Ingelogd; sessie bewaard. Titel:', await p.title());
  await b.close();
}

async function scherm(pad, uit, markeer) {
  if (!fs.existsSync(SESSIE)) throw new Error('Eerst inloggen: node tools/eblinqx_schermen.js inloggen');
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, locale: 'nl-NL', storageState: SESSIE });
  const p = await ctx.newPage();
  await p.goto(pad.startsWith('http') ? pad : BASIS + '/' + pad.replace(/^\//, ''), { waitUntil: 'networkidle' });
  if (await p.$('#frmTxtPassword')) throw new Error('Sessie verlopen: opnieuw inloggen.');
  if (markeer) {
    await p.evaluate(sel => {
      const el = document.querySelector(sel);
      if (!el) return;
      el.scrollIntoView({ block: 'center' });
      el.style.outline = '4px solid #FFCD00'; el.style.outlineOffset = '3px'; el.style.borderRadius = '4px';
    }, markeer);
  }
  await p.screenshot({ path: uit });
  console.log('Opgeslagen:', uit);
  await b.close();
}

(async () => {
  const [cmd, a, b2, c] = process.argv.slice(2);
  if (cmd === 'inloggen') await inloggen();
  else if (cmd === 'scherm') await scherm(a, b2, c);
  else console.log('Gebruik: inloggen | scherm <pad> <uitvoer.png> [selector]');
})().catch(e => { console.error('Fout:', e.message); process.exit(1); });
