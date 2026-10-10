// Reuse the disposable lab's exact quote-delegation seam. Never fetch quotes.
const fs = require('fs');
const path = '/ghostfolio/apps/api/main.js';
const source = fs.readFileSync(path, 'utf8');
const old = 'async getAssetProfile({symbol:e}){return this.yahooFinanceDataEnhancerService.getAssetProfile(e)}';
if (source.split(old).length !== 2) throw new Error('Pinned quote delegation differs');
const replacement = 'async getAssetProfile({symbol:e}){const p=JSON.parse(require("fs").readFileSync("/lab/profiles.json","utf8"));return Object.prototype.hasOwnProperty.call(p,e)?p[e]:undefined}';
fs.writeFileSync(path, source.replace(old, replacement));
