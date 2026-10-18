// app.json plus what can't be committed to a public repo: the Firebase config for push notifications
// comes from an EAS file environment variable (GOOGLE_SERVICES_JSON) at build time.
module.exports = ({ config }) => ({
  ...config,
  android: {
    ...config.android,
    ...(process.env.GOOGLE_SERVICES_JSON ? { googleServicesFile: process.env.GOOGLE_SERVICES_JSON } : {}),
  },
});
