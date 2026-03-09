const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const template = fs.readFileSync(
  path.join(__dirname, '..', 'public', 'sw.template.js'),
  'utf-8'
);

const hash = crypto.randomBytes(4).toString('hex');
const output = template.replace(/__BUILD_HASH__/g, hash);

fs.writeFileSync(
  path.join(__dirname, '..', 'public', 'sw.js'),
  output
);

console.log(`SW build hash: ${hash}`);
