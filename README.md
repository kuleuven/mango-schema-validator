# Apply ManGO metadata schemas in Python

Small application to apply metadata from a metadata schema using iRODS PRC.

## Requirements

- `python-irodsclient`
- `validators`

## Usage

```python
# authentication to iRODS
import os, os.path
from irods.session import iRODSSession
from mango_mdschema import Schema

env_file = os.getenv('IRODS_ENVIRONMENT_FILE', os.path.expanduser('~/.irods/irods_environment.json'))

# load a schema from file
my_schema = Schema('/path/to/schema') # this also validates it as a schema
with iRODSSession(irods_env_file=env_file) as session:
    obj = session.data_objects.get('path/to/my/object')
    my_metadata = {
        'text' : 'Some text',
        'a_date' : '2023-04-26',
        'author' : {
            'name' : 'Mariana',
            'email' : 'marianasemail@kuleuven.be'
        }
    }
    my_schema.apply(obj, my_metadata)
```

You can check the fields in a schema with:

```python
print(my_schema)
```

The list of required fields and default values is found as the `required_fields` attribute.
You can also check all the characteristics of a specific field such as 'name' with:

```python
my_schema.check_requirements('name') # same as print(my_schema.fields['name'])
```

You can also test the list of AVUs that would be sent by providing a given metadata dictonary with `mango_mdschema.check_metadata()` like so:

```python
from mango_mdschema import check_metadata
check_metadata(my_schema, my_metadata)
```

Check the [tutorial](tutorial/) for more details.
