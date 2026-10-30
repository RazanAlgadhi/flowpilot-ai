"""Server-owned fictional inputs for the publicly accessible demo."""
SCENARIOS = {
    'Data scientist · laptop, email, GitHub': {
        'employee': {'name': 'Mira Fenwick', 'role': 'Data Scientist', 'start_date': '2029-01-08', 'manager': 'Nolan Ashford'},
        'resources': ['laptop', 'email', 'github'],
    },
    'People operations · email': {
        'employee': {'name': 'Theo Briar', 'role': 'People Operations Specialist', 'start_date': '2029-02-12', 'manager': 'Elara Moss'},
        'resources': ['email'],
    },
    'Designer · laptop and email': {
        'employee': {'name': 'Liora Venn', 'role': 'Product Designer', 'start_date': '2029-03-19', 'manager': 'Cassian Vale'},
        'resources': ['laptop', 'email'],
    },
    'Finance analyst · profile only': {
        'employee': {'name': 'Zara Ellery', 'role': 'Finance Analyst', 'start_date': '2029-05-14', 'manager': 'Dorian Wren'},
        'resources': [],
    },
}


def request_for(scenario):
    employee = scenario['employee']
    resources = 'Request ' + ', '.join(scenario['resources']) + '.' if scenario['resources'] else 'Do not request any resources.'
    return (f"Onboard {employee['name']} as {employee['role']} starting {employee['start_date']}. "
            f"The manager is {employee['manager']}. {resources}")
