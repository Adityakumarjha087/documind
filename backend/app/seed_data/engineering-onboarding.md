# Engineering Onboarding Guide

## First Week
New engineers pair with an onboarding buddy for their first two weeks. On day one, request access
to GitHub, the cloud console and the on-call tool through the IT service desk.

## Development Workflow
All changes go through pull requests that require one approving review and a green CI build.
Branch names follow the pattern type/short-description, for example feat/export-csv. Commits use
the Conventional Commits format.

## Deployments
The main branch deploys automatically to staging. Production deployments happen through the release
pipeline on Tuesdays and Thursdays; hotfixes may be deployed any day with approval from the
engineering manager on duty.

## On-Call
Engineers join the on-call rotation after three months. Each shift lasts one week, and on-call
engineers receive a stipend of 300 USD per week. Pages must be acknowledged within 10 minutes.
