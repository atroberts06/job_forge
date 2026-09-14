---
name: grill-me
description: Interview the user relentlessly to flesh out a plan or feature design by walking the full design tree together until reaching a shared understanding, preferring codebase exploration over speculation whenever answers can be found in code.
---

# Grill Me

## Intent

Use this skill when the user wants to design, change, or debug something non-trivial and asks to be "grilled", wants help fleshing out an idea, or you detect substantial ambiguity or many possible designs.

The goal is to reach a **shared understanding** of the problem and design before writing plans, documents, or code.

## Core Principles

1. **Relentless interviewing**  
   - Ask many specific, targeted questions.  
   - Prefer small, precise questions over broad, vague ones.  
   - Do not rush to propose solutions or plans.

2. **Walk the full design tree**  
   - Treat the problem as a design tree with branches and sub-branches.  
   - For each major decision, explore key alternatives and their consequences.  
   - Walk down branches until they are concrete enough to implement.

3. **Prefer code over speculation**  
   - If a question can be answered by exploring the repo, **inspect the codebase instead of asking the user**.  
   - Use search and file reads to ground your questions and assumptions.

4. **Shared understanding before output**  
   - Do **not** generate long plans, PRDs, or big code dumps until both you and the user have a clearly aligned picture of:  
     - The problem and constraints  
     - The desired behavior and scope  
     - The main architectural choices

## Workflow

1. **Clarify the objective**
   - Restate your current understanding in 1–3 sentences.
   - Ask the user to confirm or correct it.

2. **Identify the top-level branches**
   - Ask questions to uncover the main design axes, for example:  
     - Scope vs. out-of-scope  
     - New feature vs. refactor vs. bugfix  
     - One-off change vs. reusable pattern

3. **Drill into one branch at a time**
   - Pick one branch and ask follow-ups until it is concrete.  
   - Examples:  
     - Interfaces and data shapes  
     - User flows and edge cases  
     - Performance, reliability, and security constraints
     - Documentation updates

4. **Ground in the codebase**
   - When something depends on existing behavior, search and read relevant files.  
   - Use what you find to refine or correct your questions.  
   - Call out any mismatches between current code and the user’s expectations.

5. **Summarize periodically**
   - Every several questions, summarize what is now agreed and what is still open.  
   - Ask which part to explore next.

6. **Exit condition**
   - Stop the grilling phase only when:  
     - The user explicitly says they feel understood **or**  
     - You can clearly describe the desired behavior, constraints, and main design choices in a short paragraph.
   - At that point, hand off to a planning or agent workflow if requested.

## Style Guidelines

- Bias toward **questions**, not answers.  
- Keep questions concrete and easy to answer.  
- Avoid yes/no questions when a short explanation would give more signal.  
- Be explicit about assumptions you are making as you go.