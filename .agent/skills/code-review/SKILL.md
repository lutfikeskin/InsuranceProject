---
name: code-review
description: Comprehensive checklist for conducting thorough code reviews to ensure quality, security, and maintainability.
---

# Code Review Skill

This skill provides a set of guidelines and a checklist to ensure high-quality code. You should apply these principles whenever you are modifying code, reviewing existing code, or completing a task that involves significant logic changes.

## Review Categories

### Functionality

- **Logic**: Ensure the code does exactly what it's supposed to do according to the requirements.
- **Edge Cases**: Handle unusual inputs, empty states, and boundary conditions.
- **Error Handling**: Use appropriate error handling patterns (e.g., try-except blocks, error returns).
- **Correctness**: Verify there are no obvious bugs or logic errors.

### Code Quality

- **Readability**: Code should be readable and well-structured for other developers.
- **Focused Functions**: Keep functions small and dedicated to a single task.
- **Naming**: Use descriptive and meaningful variable and function names.
- **DRY**: Avoid code duplication; extract common logic where appropriate.
- **Conventions**: Follow established project conventions and style guides.

### Security

- **Vulnerabilities**: Watch for common security flaws (e.g., SQL injection, XSS).
- **Input Validation**: Always validate or sanitize external inputs.
- **Sensitive Data**: Ensure sensitive information is handled securely and not logged.
- **Secrets**: Never hardcode secrets or credentials.

### Removing AI Code "Slop"

- **Natural Comments**: Remove redundant or overly verbose comments that a human developer wouldn't typically add.
- **Appropriate Defensiveness**: Avoid excessive try/catch blocks or defensive checks if they are not needed for the specific context.
- **Types**: Avoid using `any` or equivalent "bypass" types unless strictly necessary.
- **Consistency**: Maintain a consistent style with the surrounding codebase.
