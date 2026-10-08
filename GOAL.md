The Goal of this web app is to create a tool for completing the following workflow.

A scientist is given the full list of CMIP7 data request and needs to determine what CESM3 variables they need to include in their namelists to satisfy the request.

They ask the following questions in order:

1. Which variables are requested for my experiment? -> this should produce a list of CMIP7 compound names. Each compound maps to a list of needed CESM3 variables.
2. What are those variables by model component (since each component requires its own namelist)
3. What are the frequencies requested for each variable (since every frequency requires an entry, even for the same variable)
4. Save that list to a text file (doesnt need to be formatted for namelist yet, just variable names) that can be downloaded for each model component.