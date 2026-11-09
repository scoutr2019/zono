<?php
// Zono server settings. Change STATS_PASSWORD before uploading!
// Upload the folder "api" to public_html on zono.be, so these files are at https://zono.be/api/...
const STATS_PASSWORD = 'VERANDER-DIT-WACHTWOORD';
const SUPPORT_EMAIL = 'support@zono.be';
const MAIL_FROM = 'noreply@zono.be';          // an address on your own domain, so the mail is not seen as spam
const GITHUB_REPO = 'scoutr2019/zono';
const DATA_DIR = __DIR__ . '/data';           // protected by data/.htaccess
const REPORTS_PER_HOUR = 5;                    // per sender, against abuse
