# -*- coding: utf-8 -*-
import collections
from copy import deepcopy
from watson.form.fields import FieldMixin, File
from watson.html.elements import TagMixin, flatten_attributes
from watson.stdlib.decorators import cached_property
from watson.stdlib.imports import get_qualified_name


class Form(TagMixin):
    """<form> management.

    The implementation of the form gives the ability to define the fields
    within the form in a declarative manor.

    Usage:
        from watson.form import fields
        class MyForm(Form):
            text = fields.Text(name='text', label='My TextField')

        form = MyForm('my_form')
        form.text.value = 'Something'

        # in view
        {% form.open() %}   # <form name="my_form">
        {% form.text %}     # <input name="text" type="text" value="Something" />
        {% form.text.render_with_label() %} # <label for="text">My TextField</label><input id="text" name="text" type="text" value="Something" />
        {% form.close() %}  # </form>


    Attributes:
        dict attributes: A list of all attributes on the <form>.
    """
    attributes = None
    _valid = False
    _validated = False
    _ignored_attributes = ('fields', '_fields', 'data', 'raw_data', 'errors')
    _bound_object = None
    _bound_object_mapping = None

    def __init__(self, name, method='post', action=None, detect_multipart=True, **kwargs):
        """Inititalize the form and set some default attributes.
        """
        self.attributes = {}
        self.attributes.update(kwargs)
        self.attributes.update({
            'name': name,
            'method': method,
            'action': kwargs.get('action', '/'),
            'enctype': kwargs.get('enctype', 'application/x-www-form-urlencoded')
        })
        for field_name, field in self.fields.items():
            if detect_multipart and isinstance(field, File):
                self.attributes['enctype'] = 'multipart/form-data'
            # create a copy of the field so that we're not referencing
            # the class attr of the same name.
            setattr(self, field_name, deepcopy(field))
        del self._fields

    @property
    def validated(self):
        return self._validated

    @cached_property
    def fields(self):
        """Retrieve a list of all fields associated with the form.

        Fields are sorted based on the order that they are defined in so that
        error messages can be displayed in the correct order.
        The list of fields is cached so that it is only required to be read once.
        If the cache needs to be cleared, the _fields attribute can be deleted.

        Returns:
            OrderedDict of fields.
        """
        fields = []
        for field_name in dir(self):
            if field_name not in self._ignored_attributes and not field_name.startswith('_'):
                # ignore properties for recursion
                field = getattr(self, field_name)
                if isinstance(field, FieldMixin):
                    fields.append((field_name, field))
        fields.sort(key=lambda pair: pair[1].count)
        return collections.OrderedDict(fields)

    @cached_property
    def errors(self):
        """Returns a list of errors associated with the form.

        If the form has not been validated yet, calling this property
        will cause validation to occur.
        """
        self.is_valid()
        errors = {}
        for field_name, field in self.fields.items():
            error_list = field.errors
            if error_list:
                errors[field_name] = {'messages': field.errors,
                                      'label': field.label.text}
        return errors

    @cached_property
    def data(self):
        """Returns a dict containing all the field values.

        Used as a shorthand method to retrieve data from all the form fields
        rather than having to access the fields themselves.
        """
        return {field_name: field.value for
                field_name, field in self.fields.items()}

    @data.setter
    def data(self, data):
        """Sets the data for the form.

        Iterates through all the fields on the form and injects the value.

        Args:
            dict data: A dict of key/value pairs to populate the form with.
        """
        self.invalidate()
        data = data or {}
        for key, value in data.items():
            if key in self.fields:
                self.fields[key].value = value

    @cached_property
    def raw_data(self):
        """Returns a dict containing all the original field values.

        Field values will be their pre-filtered values.
        """
        return {field_name: field.original_value for
                field_name, field in self.fields.items()}

    def bind(self, obj=None, mapping=None, hydrate=True):
        """Binds an object to the form.

        Optionally additional mapping can be specified in order to set values on
        any of the classes that may exist within the object.
        If this method is called after the data has been set on the form, then
        the existing data will be overridden with the attributes on the object
        unless hydrate is set to false.

        Args:
            class obj: the class to bind to the form.
            dict mapping: the mapping between the form fields and obj attributes.
            bool hydrate: whether or not to hydrate the form with the obj attributes.

        Usage:
            form = ...
            user = User(username='test')
            form.bind(user)
            form.username.value  # 'test'
        """
        if obj:
            self._bound_object = obj
            if mapping:
                self._bound_object_mapping = mapping
        self.invalidate()
        if obj and hydrate:
            self.__hydrate_obj_to_form()

    # validation methods

    def invalidate(self):
        """Invalidate the data that has been bound on the form.

        This is called automatically when data is bound to the form and
        sets the forms validity to invalid.
        """
        attrs = ('_data', '_raw_data', '_errors')
        for attr in attrs:
            try:
                delattr(self, attr)
            except AttributeError:
                pass
        self._validated = self._valid = False

    def is_valid(self):
        """Determine whether or not the form and relating values are valid.

        Filter all the values on the fields associated with the form, and
        then validate each field. Will only execute the filter/validation
        steps if the form has not been previously validated, or has
        been invalidated.

        Returns:
            boolean value depending on the validity of the form.
        """
        if not self._validated:
            self._valid = True
            for field_name, field in self.fields.items():
                field.filter()
                valid = field.validate()
                if len(valid) > 0:
                    self._valid = False
            self._validated = True
        if self._valid and self._bound_object:
            self.__hydrate_form_to_obj()
        return self._valid

    # rendering methods

    def open(self):
        """Render the start tag of the form.
        """
        return '<form {0}>'.format(flatten_attributes(self.attributes))

    def close(self):
        """Render the end tag of the form.
        """
        return '</form>'

    # convenience methods

    @property
    def name(self):
        return self.attributes['name']

    @property
    def method(self):
        return self.attributes['method']

    @property
    def action(self):
        return self.attributes['action']

    @property
    def enctype(self):
        return self.attributes['enctype']

    # hydration methods

    def __hydrate_obj_to_form(self):
        # should never be called externally. Triggered by bind.
        obj_mapping = self._bound_object_mapping or {}
        for field_name, field in self.fields.items():
            attr = field_name
            current_obj = self._bound_object
            if field_name in obj_mapping:
                last_field = obj_mapping[field_name][-1]
                for name in obj_mapping[field_name][0:-1]:
                    try:
                        current_obj = getattr(current_obj, name)
                    except:
                        raise AttributeError('Mapping for object does not match object structure.')
            if hasattr(current_obj, attr):
                self.fields[field_name].value = getattr(current_obj, attr)

    def __hydrate_form_to_obj(self):
        # should never be called externally. Triggered by is_valid.
        obj_mapping = self._bound_object_mapping or {}
        for field_name, value in self.data.items():
            current_obj = self._bound_object
            attr = field_name
            if field_name in obj_mapping:
                attr = obj_mapping[field_name][-1]
                for name in obj_mapping[field_name][0:-1]:
                    try:
                        current_obj = getattr(current_obj, name)
                    except:
                        raise AttributeError('Mapping for object does not match object structure.')
            if hasattr(current_obj, attr):
                setattr(current_obj, attr, value)

    def __len__(self):
        """Return the number of fields associated with the form.
        """
        return len(self.fields)

    def __repr__(self):
        return '<{0} name:{1} method:{2} action:{3} fields:{4}>'.format(
            get_qualified_name(self),
            self.name,
            self.method,
            self.action,
            len(self))


class MultipartForm(Form):
    """Convenience class for forms that should be multipart/form-data.

    By default, the Form class will automatically detect whether or not
    a field is of type file, and convert it to multipart.
    """
    def __init__(self, name, method='post', action=None, **kwargs):
        kwargs['enctype'] = 'multipart/form-data'
        super(MultipartForm, self).__init__(name, method, action, **kwargs)
