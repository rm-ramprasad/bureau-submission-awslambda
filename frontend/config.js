// Local development: no sign-in (the API runs with SUBMISSIONS_AUTH=none).
// On AWS the deploy script replaces this file with the Cognito settings, e.g.
// window.APP_CONFIG = { auth: "cognito", authority: "https://cognito-idp.ap-south-1.amazonaws.com/<pool id>",
//                       clientId: "<app client id>", domain: "https://<prefix>.auth.ap-south-1.amazoncognito.com" };
window.APP_CONFIG = { auth: "none" };
