# KeyCRM lead push

How to make the KeyCRM mobile app notify a manager when a lead is new, using the product’s own task push instead of a custom mobile channel.

## Problem

KeyCRM does not send a distinct “new lead” push, and its OpenAPI cannot push to the phone or create a free-form notification. Managers were missing leads that sat in the “New” status until someone opened the desktop pipeline.

## What was built

A short, operational design and the scripts around it.

KeyCRM’s supported path is: a trigger on a new lead (status “New”) creates a task for the owner. The mobile app already pushes task notifications, so the lead shows up as a task. The notes in this repository spell out that OpenAPI has no task-create endpoint for this and no mobile push API, and they list the trigger steps inside KeyCRM itself.

The `src/` and `deploy/` folders hold the helper that watches the pipeline and the notes for putting it on a server. Logs are local and are not required to read the design.

## How it works

1. A lead enters the pipeline in the “New” status.
2. A KeyCRM trigger creates a task assigned to the responsible user.
3. The phone notifies that user about the task.
4. Opening the task opens the lead.

That is the whole mechanism. A separate push service would not be able to reach the official app.

## Stack

KeyCRM triggers and OpenAPI. Helper scripts in this repository.

## Run locally

Copy the env example if the helper is used, and set the KeyCRM token only in your own `.env`. Do not commit it.

## What this public copy leaves out

`.env` and runtime logs.
