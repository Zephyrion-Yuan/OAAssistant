# Playwright Post-Login Mode

This project uses privacy-first post-login automation.

Core rules:

- Launch a dedicated Playwright-controlled Microsoft Edge profile.
- The user completes company SSO manually inside that dedicated profile.
- Automation opens stable post-login business URLs only after authentication.
- Automation operates only on configured whitelisted domains.
- Automation fills only configured fields.
- Automation must not submit forms in MVP; user reviews and submits manually.

Do not implement:

- DingTalk SSO link interception.
- One-time SSO URL replay.
- Cookie import/export from normal Edge.
- Token, SAML, OAuth code, password, or MFA capture.
- Remote debugging ports by default.
- Automatic submit/approve/pay/delete/send actions.

The safe flow is:

Manual login in dedicated Playwright Edge profile -> stable business URL -> configured form fill -> visible review overlay -> manual submit.
