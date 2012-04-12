#!/usr/bin/env python

# Copyright (c) 2011, Dorian Scholz, TU Darmstadt
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#   * Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#   * Redistributions in binary form must reproduce the above
#     copyright notice, this list of conditions and the following
#     disclaimer in the documentation and/or other materials provided
#     with the distribution.
#   * Neither the name of the TU Darmstadt nor the names of its
#     contributors may be used to endorse or promote products derived
#     from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

from __future__ import division
import math, random, time # used for the expression eval context

import rosgui.QtBindingHelper #@UnusedImport
from QtCore import Slot, qDebug, QObject, QSignalMapper, Qt, QTimer, qWarning

import roslib
roslib.load_manifest('rosgui_publisher')
import rospy
import PublisherWidget
reload(PublisherWidget)

class Publisher(QObject):

    def __init__(self, context):
        super(Publisher, self).__init__()
        self.setObjectName('Publisher')

        # create widget
        self._widget = PublisherWidget.PublisherWidget()
        self._widget.add_publisher.connect(self.add_publisher)
        self._widget.change_publisher.connect(self.change_publisher)
        self._widget.publish_once.connect(self.publish_once)
        self._widget.remove_publisher.connect(self.remove_publisher)
        self._widget.clean_up_publishers.connect(self.clean_up_publishers)
        if context.serial_number() > 1:
            self._widget.setWindowTitle(self._widget.windowTitle() + (' (%d)' % context.serial_number()))

        # create context for the expression eval statement
        self._eval_locals = {}
        for module in (math, random, time):
            self._eval_locals.update(module.__dict__)
        del self._eval_locals['__name__']
        del self._eval_locals['__doc__']

        self._publishers = {}
        self._id_counter = 0

        self._timeout_mapper = QSignalMapper(self)
        self._timeout_mapper.mapped[int].connect(self.publish_once)

        # add our self to the main window
        context.add_widget(self._widget)


    @Slot(str, str, float, bool)
    def add_publisher(self, topic_name, type_name, rate, enabled):
        publisher_info = {
            'topic_name': str(topic_name),
            'type_name': str(type_name),
            'rate': float(rate),
            'enabled': bool(enabled),
        }
        self._add_publisher(publisher_info)


    def _add_publisher(self, publisher_info):
        publisher_info['publisher_id'] = self._id_counter
        self._id_counter += 1
        publisher_info['counter'] = 0
        publisher_info['enabled'] = publisher_info.get('enabled', False)
        publisher_info['expressions'] = publisher_info.get('expressions', {})

        publisher_info['message_instance'] = self._create_message_instance(publisher_info['type_name'])
        if publisher_info['message_instance'] is None:
            return

        # create publisher and timer
        publisher_info['publisher'] = rospy.Publisher(publisher_info['topic_name'], type(publisher_info['message_instance']))
        publisher_info['timer'] = QTimer(self)

        # add publisher info to _publishers dict and create signal mapping  
        self._publishers[publisher_info['publisher_id']] = publisher_info
        self._timeout_mapper.setMapping(publisher_info['timer'], publisher_info['publisher_id'])
        publisher_info['timer'].timeout.connect(self._timeout_mapper.map)
        if publisher_info['enabled'] and publisher_info['rate'] > 0:
            publisher_info['timer'].start(int(1000.0 / publisher_info['rate']))

        self._widget.publisher_tree_widget.model().add_publisher(publisher_info)


    @Slot(int, str, str, str, object)
    def change_publisher(self, publisher_id, topic_name, column_name, new_value, setter_callback):
        handler = getattr(self, '_change_publisher_%s' % column_name, None)
        if handler is not None:
            new_text = handler(self._publishers[publisher_id], topic_name, new_value)
            if new_text is not None:
                setter_callback(new_text)


    def _change_publisher_enabled(self, publisher_info, topic_name, new_value):
        publisher_info['enabled'] = (new_value and new_value.lower() in ['1', 'true', 'yes'])
        qDebug('Publisher._change_publisher_enabled(): %s enabled: %s' % (publisher_info['topic_name'], publisher_info['enabled']))
        if publisher_info['enabled'] and publisher_info['rate'] > 0:
            publisher_info['timer'].start(int(1000.0 / publisher_info['rate']))
        else:
            publisher_info['timer'].stop()
        return '%s' % publisher_info['enabled']


    def _change_publisher_type(self, publisher_info, topic_name, new_value):
        type_name = new_value
        # create new slot
        slot_value = self._create_message_instance(type_name)

        # find parent slot
        slot_path = topic_name[len(publisher_info['topic_name']):].strip('/').split('/')
        parent_slot = eval('.'.join(["publisher_info['message_instance']"] + slot_path[:-1]))

        # find old slot
        slot_name = slot_path[-1]
        slot_index = parent_slot.__slots__.index(slot_name)

        # restore type if user value was invalid
        if slot_value is None:
            qDebug('Publisher._change_publisher_type(): could not find type: %s' % (type_name))
            return parent_slot._slot_types[slot_index]

        else:
            # replace old slot
            parent_slot._slot_types[slot_index] = type_name
            setattr(parent_slot, slot_name, slot_value)

            self._widget.publisher_tree_widget.model().update_publisher(publisher_info)


    def _change_publisher_rate(self, publisher_info, topic_name, new_value):
        try:
            rate = float(new_value)
        except Exception:
            qDebug('Publisher._change_publisher_rate(): could not parse rate value: %s' % (new_value))
        else:
            publisher_info['rate'] = rate
            qDebug('Publisher._change_publisher_rate(): %s rate changed: %fHz' % (publisher_info['topic_name'], publisher_info['rate']))
            publisher_info['timer'].stop()
            if publisher_info['enabled'] and publisher_info['rate'] > 0:
                publisher_info['timer'].start(int(1000.0 / publisher_info['rate']))
        # make sure the column value reflects the actual rate
        return '%.2f' % publisher_info['rate']


    def _change_publisher_expression(self, publisher_info, topic_name, new_value):
        if len(new_value) == 0:
            if topic_name in publisher_info['expressions']:
                del publisher_info['expressions'][topic_name]
                qDebug('Publisher._change_publisher_expression(): removed expression for: %s' % (topic_name))
        else:
            publisher_info['expressions'][topic_name] = new_value
            qDebug('Publisher._change_publisher_expression(): %s expression: %s' % (topic_name, new_value))


    def _extract_array_info(self, type_str):
        array_size = None
        if '[' in type_str and type_str[-1] == ']':
            type_str, array_size_str = type_str.split('[', 1)
            array_size_str = array_size_str[:-1]
            if len(array_size_str) > 0:
                array_size = int(array_size_str)
            else:
                array_size = 0

        return type_str, array_size


    def _create_message_instance(self, type_str):
        base_type_str, array_size = self._extract_array_info(type_str)

        base_message_type = roslib.message.get_message_class(base_type_str)
        if array_size is not None:
            message = []
            for _ in range(array_size):
                message.append(base_message_type())
        else:
            message = base_message_type()
        return message


    def _evaluate_expression(self, expression, slot_type):
        successful_eval = True
        successful_conversion = True

        try:
            # try to evaluate expression
            value = eval(expression, {}, self._eval_locals)
        except Exception:
            # just use expression-string as value
            value = expression
            successful_eval = False

        try:
            # try to convert value to right type
            value = slot_type(value)
        except Exception:
            successful_conversion = False

        if successful_conversion:
            return value
        elif successful_eval:
            qWarning('Publisher._evaluate_expression(): can not convert expression to slot type: %s -> %s' % (type(value), slot_type))
        else:
            qWarning('Publisher._evaluate_expression(): failed to evaluate expression: %s' % (expression))

        return None


    def _fill_message_slots(self, message, topic_name, expressions, counter):
        if topic_name in expressions and len(expressions[topic_name]) > 0:

            # get type
            if hasattr(message, '_type'):
                message_type = message._type
            else:
                message_type = type(message)

            self._eval_locals['i'] = counter
            value = self._evaluate_expression(expressions[topic_name], message_type)
            return value

        # if no expression exists for this topic_name, continue with it's child slots
        elif hasattr(message, '__slots__'):
            for slot_name in message.__slots__:
                value = self._fill_message_slots(getattr(message, slot_name), topic_name + '/' + slot_name, expressions, counter)
                if value is not None:
                    setattr(message, slot_name, value)

        elif type(message) in (list, tuple) and (len(message) > 0) and hasattr(message[0], '__slots__'):
            for index, slot in enumerate(message):
                self._fill_message_slots(slot, topic_name + '[%d]' % index, expressions, counter)

        return None


    @Slot(int)
    def publish_once(self, publisher_id):
        publisher_info = self._publishers.get(publisher_id, None)
        if publisher_info is not None:
            publisher_info['counter'] += 1
            self._fill_message_slots(publisher_info['message_instance'], publisher_info['topic_name'], publisher_info['expressions'], publisher_info['counter'])
            publisher_info['publisher'].publish(publisher_info['message_instance'])


    @Slot(int)
    def remove_publisher(self, publisher_id):
        publisher_info = self._publishers.get(publisher_id, None)
        if publisher_info is not None:
            publisher_info['timer'].stop()
            publisher_info['publisher'].unregister()
            del self._publishers[publisher_id]


    def save_settings(self, global_settings, perspective_settings):
        publisher_copies = []
        for publisher in self._publishers.values():
            publisher_copy = {}
            publisher_copy.update(publisher)
            publisher_copy['enabled'] = False
            del publisher_copy['timer']
            del publisher_copy['message_instance']
            del publisher_copy['publisher']
            publisher_copies.append(publisher_copy)
        perspective_settings.set_value('publishers', repr(publisher_copies))


    def restore_settings(self, global_settings, perspective_settings):
        publishers = eval(perspective_settings.value('publishers', '[]'))
        for publisher in publishers:
            self._add_publisher(publisher)


    def clean_up_publishers(self):
        self._widget.publisher_tree_widget.model().clear()
        for publisher_info in self._publishers.values():
            publisher_info['timer'].stop()
            publisher_info['publisher'].unregister()
        self._publishers = {}


    def shutdown_plugin(self):
        self.clean_up_publishers()
