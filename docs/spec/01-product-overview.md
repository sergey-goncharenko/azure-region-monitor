# Product Overview

## Summary
The Azure Regional Feature Availability Monitor is a public service that continuously tests Azure regions for real-world feature availability and publishes structured results, diffs, and alerts.

## Core Value
Microsoft does not publish real-time rollout telemetry for:
- AKS extensions
- Azure Functions runtime versions
- Container Apps Dapr versions
- Azure OpenAI model availability
- App Service Linux feature rollout

This project fills that gap by providing:
- Continuous synthetic testing
- Public dashboards
- Alerts when features become available or regress
- APIs for SaaS companies to automate region expansion
