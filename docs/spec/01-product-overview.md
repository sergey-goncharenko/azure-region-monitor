# Product Overview

## Summary
The Azure Regional Feature Availability Monitor is a public service that continuously tests Azure regions for real-world feature availability and publishes structured results, diffs, and alerts.

## Core Value
Microsoft does not publish real-time rollout telemetry for:
- AKS extensions
- Azure Functions runtime versions
- VM SKU regional availability
- Container Apps Dapr versions
- Azure OpenAI model availability
- App Service Linux feature rollout

This project fills that gap by providing:
- Continuous synthetic testing
- Public dashboards
- Human-readable methodology for status semantics
- Alerts when features become available or regress
- APIs for SaaS companies to automate region expansion

Current implemented signals are read-only listings for AKS extension types, AKS Kubernetes versions, Azure Functions Flex Consumption locations and Linux runtimes, Container Apps Microsoft.App provider resource type locations, and VM SKUs. These signals show advertised regional rollout evidence; they do not by themselves prove quota, capacity, or deployment success.
