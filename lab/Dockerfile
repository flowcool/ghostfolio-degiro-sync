# Same pinned native application as the existing disposable acceptance lab.
FROM ghostfolio/ghostfolio:3.81.0@sha256:7c925671dba267cc2175195f064b42b9733f3ea170a21db488b7d2be3319e088
LABEL io.flowcool.degiro-lab="persistent-v1"
COPY patch_profile.cjs /lab/patch_profile.cjs
RUN node /lab/patch_profile.cjs
