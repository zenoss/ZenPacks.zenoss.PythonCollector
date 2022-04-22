
Background
------------------------------

This *ZenPack* provides a new *Python* data source type. It also provides a new *zenpython* collector daemon that is 
responsible for collecting these data sources.



Usage
---------------------

This zenpack adds a new *zenpython* collector daemon. In most cases there is nothing you need to know about to make use 
of this additional collector functionality. The following sections describe available configuration, troubleshooting 
and tuning information.


### ZenPython Configuration Options

The following options can be specified in the zenpython configuration file. Typically, the default values for these 
options are appropriate and don't need to be adjusted.

**blockingwarning**
:   The zenpython collector daemon executes plugin code provided by other ZenPacks. If this plugin code blocks for too 
    long it will prevent zenpython from performing other tasks including collecting other datasources while the plugin 
    code is executed. The `blockingwarning` option will cause zenpython to log a warning for any plugin code that blocks 
    for the configured number of seconds or more. The default value is 3 seconds. Decimal precision such as 3.5 can be 
    used.

**blockingtimeout**
:   See `blockingwarning`. This option will cause zenpython to disable a plugin if it blocks for longer than the number 
    of seconds specified. The zenpython daemon will restart itself after disabling the plugin to get unblocked. Events 
    will be created indicating that some monitoring will not be performed due to disabled plugins on all affected 
    devices. The default value is 30 seconds. Decimal precision such as 5.5 can be used.
    A blocking plugin likely indicates a problem with the way the plugin was written. The author of the plugin should 
    be contacted if this is seen. Zenoss support should be contacted if the plugin came from Zenoss.
    Once a plugin is blocked, it will remain permanently blocked until its name is removed from either 
    `/var/zenoss/zenpython.blocked` on Zenoss Cloud and Zenoss 6, or `/opt/zenoss/var/zenpython.blocked` on Zenoss 4. 
    The zenpython service must be restarted after manual modifications to this file.

**runningtimeout**
:   Timeout datasource collection that exceeds (runningtimeout * cycletime) seconds. The default value is 3 cycles. 
    Decimal precision such as 3.5 can be used. A 0 value will disable datasource timeouts as was the case in 
    PythonCollector versions earlier than 1.10.0.


**twistedthreadpoolsize**
:   Controls size of threads pool. Datasources can use multi-threading to run multiple requests in parallel. Increasing 
    this value may boost performance at the cost of system memory used. The default value is 10.

**twistedconcurrenthttp**
:   Controls the number of total concurrent HTTP connections to be permitted by the twisted.web.client.getPage function.

**collect**
:   Allows only specific plugins to run. This is primarily a developer option to help reduce the noise while developing 
    plugins. The default is to collect all configured plugins. The value for this option is a regular expression. Only 
    plugins which class name matches the regular expression will be run.

**ignore**
:   Prevents specific plugins from running. This is primarily a developer option to help reduce the noise while 
    developing plugins. The default is to not ignore any configured plugins. The value for this option is a regular 
    expression. Only plugins which class name doesn't match the regular expression will be run.

**datasource**
:   Collects only the specified datasource. The format is "template/datasource". For example, collecting for a network 
    interface component on a Windows server: `ethernetCsmacd/bytesSentSec`.


### ZenPython Statistics

There are two kinds of statistics available from the *zenpython* collector daemon. There are datapoints which can be 
plotted on graphs and have thresholds defined, and there are detailed task statistics that can be logged.

#### Datapoints

The following standard collector datapoints are available for *zenpython*. These datapoints are provided by the Zenoss 
platform and may differ depending on which version of Zenoss is being used.

- **devices**: Number of devices being collected.
- **dataPoints**: Number of datapoints collected per second.
- **eventCount**: Number of events sent per second.
- **discardedEvents**: Number of events discarded per second.
- **eventQueueLength**: Number of events queued to be set to *zenhub*.
- **taskCount**: Total number of configured tasks.
- **runningTasks**: Number of tasks in the running state.
- **queuedTasks**: Number of tasks queued waiting to be run.
- **missedRuns**: Number of tasks that missed their scheduled run time.

The following additional collector datapoonts are available for *zenpython*. These datapoints are provided by the 
collector daemon and may differ depending on which version of PythonCollector is being used.

- **percentBlocked**: Percent of the time blocked by plugin code execution.
- **timedOutTasks**: Tasks timed out by runningtimeout per second.


#### Task Statistics

The datapoints above provide for a good high-level understanding of the overall trends for the *zenpython* collector 
daemon. When certain datapoints show a potential problem it can often be useful to capture detailed per-task statistics 
to identify which tasks are contributing to the problem.

The *zenpython* process will dump detailed per-task information to its regular log file if it sent the SIGUSR2 signal. 
Depending on the Zenoss version being used, different utilities are provided for invoking this signal.

- Zenoss Cloud and Zenoss 6: `serviced service action zenpython stats`
- Zenoss 4: `zenpython stats`

Running those commands won't produce any direct output. You must look at the *zenpython* log to see the resulting 
statistics.


Developing Plugins
---------------------

The goal of the Python data source type is to replicate some standard *COMMAND* data source type's functionality without 
requiring a new shell and shell subprocess to be spawned each time the data source is collected. The *COMMAND* data 
source type is infinitely flexible, but because of the shell and subprocess spawning, it's performance and ability to 
pass data into the collection script are limited. The *Python* data source type circumvents the need to spawn 
subprocesses by forcing the collection code to be asynchronous using the Twisted library. It circumvents the problem 
with passing data into the collection logic by being able to pass any basic Python data type without the need to worry 
about shell escaping issues.

The *Python* data source type is intended to be used in one of two ways. The first way is directly through the creation 
of *Python* data sources through the web interface or in a ZenPack. When used in this way, it is the responsibility of 
the data source creator to implement the required *Python* class specified in the data source's *Python Class Name* 
property field. The second way the *Python* data source can be used is as a base class for another data source type. 
Used in this way, the ZenPack author will create a subclass of *PythonDataSource* to provide a higher-level 
functionality to the user. The user is then not responsible for writing a *Python* class to collect and process data.


### Using the Python Data Source Type Directly

To create a *Python* data source directly you should first implement the *Python* class you'll eventually use for the 
data source's *Plugin Class Name*. It is recommended to implement this class in a ZenPack so that it is portable from 
one Zenoss system to another and differentiates your custom code from Zenoss code.

Assuming you have a ZenPack named `ZenPacks.example.PackName` you would create a 
`ZenPacks/example/PackName/dsplugins.py` file with contents like the following.

```[python]
import time

from Products.ZenEvents import ZenEventClasses

from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import PythonDataSourcePlugin


class MyPlugin(PythonDataSourcePlugin):
    """Explanation of what MyPlugin does."""

    # List of device attributes you'll need to do collection.
    proxy_attributes = (
        'zCommandUsername',
        'zCommandPassword',
    )

    @classmethod
    def config_key(cls, datasource, context):
        """
        Return a tuple defining collection uniqueness.

        This is a classmethod that is executed in zenhub. The datasource and
        context parameters are the full objects.

        This example implementation is the default. Split configurations by
        device, cycle time, template id, datasource id and the Python data
        source's plugin class name.

        You can omit this method from your implementation entirely if this
        default uniqueness behavior fits your needs. In many cases it will.
        """
        return (
            context.device().id,
            datasource.getCycleTime(context),
            datasource.rrdTemplate().id,
            datasource.id,
            datasource.plugin_classname,
        )

    @classmethod
    def params(cls, datasource, context):
        """
        Return params dictionary needed for this plugin.

        This is a classmethod that is executed in zenhub. The datasource and
        context parameters are the full objects.

        This example implementation will provide no extra information for
        each data source to the collect method.

        You can omit this method from your implementation if you don't require
        any additional information on each of the datasources of the config
        parameter to the collect method below. If you only need extra
        information at the device level it is easier to just use
        proxy_attributes as mentioned above.
        """
        return {}

    def collect(self, config):
        """
        No default collect behavior. You must implement this method.

        This method must return a Twisted deferred. The deferred results will
        be sent to the onResult then either onSuccess or onError callbacks
        below.
        """
        ds0 = config.datasources[0]
        return somethingThatReturnsADeferred(
            username=ds0.zCommandUsername,
            password=ds0.zCommandPassword
        )

    def onResult(self, result, config):
        """
        Called first for success and error.

        You can omit this method if you want the result of the collect method
        to be used without further processing.
        """
        return result

    def onSuccess(self, result, config):
        """
        Called only on success. After onResult, before onComplete.

        You should return a data structure with zero or more events, values,
        metrics, and maps.
        """
        collectionTime = time.time()
        return {
            'events': [
                {
                    'summary': 'successful collection',
                    'eventKey': 'myPlugin_result',
                    'severity': ZenEventClasses.Clear,
                },
                {
                    'summary': 'first event summary',
                    'eventKey': 'myPlugin_result',
                    'severity': ZenEventClasses.Info,
                },
                {
                    'summary': 'second event summary',
                    'eventKey': 'myPlugin_result',
                    'severity': ZenEventClasses.Warning,
                }
            ],

            'values': {
                None: {
                    # datapoints for the device (no component)
                    'datasource1_datapoint1': (123.4, collectionTime),
                    'datasource1_datapoint2': (5.678, collectionTime),
                },
                'cpu1': {
                    # datapoints can be specified per datasource...
                    'datasource1_user': (12.1, collectionTime),
                    'datasource2_user': (13.2, collectionTime),
                    # or just by id
                    'datasource1_system': (1.21, collectionTime),
                    'io': (23, collectionTime),
                }
            },

            'metrics': [
                self.new_metric(
                    name="adhoc.metric1",
                    value=6.78,
                    timestamp=collectionTime,  # optional, default is now
                    tags={  # optional, default is {}
                        "anything": "you want",
                    }
                ),
            ],

            'maps': [
                ObjectMap(...),
                RelationshipMap(..),
            ],
    
            # Optional attribute, in most cases it's used when you want to 
            # change the execution interval of a task during the data 
            # collection.
            'interval': 300,
        }

        def onError(self, result, config):
            """
            Called only on error. After onResult, before onComplete.
    
            You can omit this method if you want the error result of the collect
            method to be used without further processing. It recommended to
            implement this method to capture errors.
            """
            return {
                'events': [
                    {
                        'summary': 'error: %s' % result,
                        'eventKey': 'myPlugin_result',
                        'severity': 4,
                    }
                ],
            }

        def onComplete(self, result, config):
            """
            Called last for success and error.
    
            You can omit this method if you want the result of either the
            onSuccess or onError method to be used without further processing.
            """
            return result

        def cleanup(self, config):
            """
            Called when collector exits, or task is deleted or changed.
            """
            return

```


#### Types of Data

A PythonDataSourcePlugin has the ability to publish four types of data: events, values, metrics, and maps.


#### Events

Events are straightforward. They are the events that end up in the Zenoss event console. When publishing from a plugin 
they are expected to be supplied as a list of dictionaries where each dictionary looks as follows.

```[python]
events = [
    {
        "device": "DEVICE_ID",
        "component": "COMPONENT_ID",
        "severity": 2,
        "summary": "a brief (128 characters or less) summary of the event",
        "message": "additional text that can be lengthy",
        "eventKey": "stringUniqueToTypeOfEvent",
        "eventClassKey": "stringToAidInMappingEvent",
        "rcvtime": 1539978022
    }
]
```

Only the *summary*, and *severity* fields are required. The *device* field will be automatically filled by *zenpython* 
if not specified. As many arbitrary additional fields as desired may be added to the event.


#### Values

Values are values for configured datapoints. When publishing from a plugin they are expected to be supplied as 
dictionary of dictionaries that looks like the following example.

```[python]
values = {
    None: {
        # datapoints for the device (no component)
        'datasource1_datapoint1': (123.4, collectionTime),
        'datasource1_datapoint2': (5.678, collectionTime)
    },
    'cpu1': {
        # datapoints can be specified per datasource.
        'datasource1_user': (12.1, collectionTime),
        'datasource2_user': (13.2, collectionTime),
        # or just by id
        'io': (23, collectionTime),
        # collectionTime is optional. Now is assumed.
        'datasource1_system": 1.21
    }
}
```

#### Metrics

Metrics are ad hoc metrics that don't have to be associated with any datapoint. They are primarily useful in Zenoss 
Cloud where there are tools for visualizing metrics that have no pre-configured datapoints and graphs to show those 
datapoints. When publishing from a plugin they are expected to be supplied as a list of *Metric* objects. These *Metric* 
objects are created using the `self.new_metric(name, value, timestamp, tags)` method as follows.

```[python]
[
    self.new_metric(
        name="adhoc.metric1",
        value=6.78,
        timestamp=collectionTime,    # optional, default is now
        tags={                       # optional, default is {}
            "anything": "you want"
        }
    )
]
```

Typically, ad hoc metrics are only useful in Zenoss Cloud. Due to this you may want to set the *'no-store'* tag to 
*'true'* to avoid having it stored in the collection zone where it won't be useful. It will still be forwarded to Zenoss 
Cloud.


#### Maps

Maps are *DataMaps* which are Zenoss' mechanism for supplying model data. When publishing from a plugin they are 
expected to be supplied as a list of *ObjectMap* and/or *RelationshipMap* objects as follows.

```[python]
[
    ObjectMap(
        data={
            "snmpSysName": "the system's name",
            "snmpSysDescr": "a description of the system"
        }
    ),

    ObjectMap(
        compname="hw",
        data={
            "totalMemory": 34359738368
        }
    ),

    ObjectMap(
        compname="os",
        data={"totalSwap": 0}
    ),

    RelationshipMap(
        compname="os",
        relname="interfaces",
        modname="Products.ZenModel.IpInterface",
        objmaps=[
            {
                "id": "eth0",
                "interfaceName": "eth0",
                "speed": 10000000000,
                "ifType": "ethernetCsmacd",
            }
        ]
    ),
]
```


### Publishing Data Immediately

In the *MyPlugin* example above you will see that data (events, values, metrics, maps) are returned from the 
*onSuccess*, *onError*, etc. methods. These methods are only executed when the Deferred returned by the *collect* method 
completes. The *collect* method is executed by *zenpython* once per cycle time of the associated datasources. Normally 
this is desirable as it allows data to be collected on a predetermined schedule. However, there are cases where you may 
get data at unpredictable times, and would like to publish that data immediately without waiting for the *collect* 
method to be called again. There are a number of additional methods available to *PythonDataSourcePlugin* classes that 
make this possible.

The following methods are available to *PythonDataSourcePlugin* for immediate data publishing.

- `publishEvents(events : List[dict])`
- `publishValues(values : Dict[dict])`
- `publishMetrics(metrics : List[Metric])`
- `publishMaps(maps : List[DataMap])`
- `publishData(data : Dict[Any])`

Additionally, there is a `changeInterval(interval : int)` method to change the collection interval.

These methods allow for all the same capabilities of the *data* dictionary returned by *on** methods, but done outside 
the predetermined collection interval.


#### Examples

See the following example of a plugin that uses immediate publishing. This example is simplified. See the above example 
for a more complete example for necessary imports, and other options.

```[python]
from twisted.internet import defer
from somewhere import MyListener


class MyPlugin(PythonDataSourcePlugin):
    listener = None

    def collect(self, config):
        if not self.listener:
            self.listener = MyListener(
                config=config,
                callback=self.onDataReceived
            )

        if not self.listener.running:
            self.listener.start()

        return defer.succeed(None)

    def cleanup(self, config):
        if self.listener:
            self.listener.stop()

    def onDataReceived(self, data):
        self.publishData(data)
```

In the above example our plugin's `collect` method is only responsible for creating and starting a listener that can get 
data at any time. When it gets data, it is immediately published by the callback: `onDataReceived`.


### Extending the Python Data Source Type

To extend the *Python* data source type to create a new data source type you will absolutely need to create a ZenPack to 
contain your new data source type. Assuming you have a ZenPack named `ZenPacks.example.PackName` you would create a 
`ZenPacks/example/PackName/datasources/MyDataSource.py` file with contents like the following.

```[python]
from zope.component import adapts
from zope.interface import implements

from Products.Zuul.form import schema
from Products.Zuul.infos import ProxyProperty
from Products.Zuul.infos.template import RRDDataSourceInfo
from Products.Zuul.interfaces import IRRDDataSourceInfo
from Products.Zuul.utils import ZuulMessageFactory as _t

from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import PythonDataSource, PythonDataSourcePlugin


class MyDataSource(PythonDataSource):
    """Explanation of what MyDataSource does."""

    ZENPACKID = 'ZenPacks.example.PackName'

    # Friendly name for your data source type in the drop-down selection.
    sourcetypes = ('MyDataSource',)
    sourcetype = sourcetypes[0]

    # Collection plugin for this type. Defined below in this file.
    plugin_classname = 'ZenPacks.example.PackName.datasources.MyDataSource.MyDataSourcePlugin'

    # Extra attributes for my type.
    extra1 = ''
    extra2 = ''

    # Registering types for my attributes.
    _properties = PythonDataSource._properties + (
        {'id': 'extra1', 'type': 'string'},
        {'id': 'extra2', 'type': 'string'},
    )


class IMyDataSourceInfo(IRRDDataSourceInfo):
    """Interface that creates the web form for this data source type."""

    cycletime = schema.TextLine(
        title=_t(u'Cycle Time (seconds)'))

    extra1 = schema.TextLine(
        group=_t('MyDataSource'),
        title=_t('Extra 1'))

    extra2 = schema.TextLine(
        group=_t('MyDataSource'),
        title=_t('Extra 1'))


class MyDataSourceInfo(RRDDataSourceInfo):
    """Adapter between IMyDataSourceInfo and MyDataSource."""

    implements(IMyDataSourceInfo)
    adapts(MyDataSource)

    testable = False

    cycletime = ProxyProperty('cycletime')

    extra1 = ProxyProperty('extra1')
    extra2 = ProxyProperty('extra2')


class MyDataSourcePlugin(PythonDataSourcePlugin):
    """
    Collection plugin class for MyDataSource.

    See the "Using the Python Data Source Type Directly" section above for
    an example implementation.
    """
    pass
```


### Updating the Model

Usually the job of updating the model is performed by modeler plugins being run by the *zenmodeler* service. However, it 
is also possible to perform the same type of model updates with a `PythonDataSourcePlugin`.

**Note:** Model updates are much more expensive operations than creating events or collecting datapoints. It is better 
to perform as much modeling as possible using modeler plugins on their typical 12-hour interval, and perform only the 
absolutely necessary smaller model updates more frequently using a `PythonDataSourcePlugin`. Too much modeling activity 
can result in the degradation of a Zenoss' systems overall performance.

Model data in the form of *DataMaps* can be returned from any of the following methods of a `PythonDataSourcePlugin`.

- collect
- onResult
- onSuccess
- onError
- onComplete

Which of these you choose to implement will dictate which should return *DataMaps*. We'll focus on the simple case of 
only the *collect* method being implemented.

The following example demonstrates a *collect* method that returns *maps*. It's *maps* that contains a list of 
*DataMaps*. A *DataMap* can be either an *ObjectMap* or *RelationshipMap* depending on whether you're intended to update 
the model of a single object, or an entire relationship of objects.

```[python]
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap

from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import \
    PythonDataSourcePlugin


class MyDataSourcePlugin(PythonDataSourcePlugin):
    def collect(self, config):
        return {
            'maps': [

                # An ObjectMap with no compname or relname will be
                # applied to the device.
                ObjectMap(
                    {
                        'rackSlot': 'near-the-top'
                    }
                ),

                # An ObjectMap with a compname, but no relname will be
                # applied to a static object that's always a child of the
                # device. For example: hw and os.
                ObjectMap(
                    {
                        'compname': 'hw',
                        'totalMemory': 45097156608
                    }
                ),

                # An ObjectMap with an id, relname, and modname will be
                # applied to a component of the device. The component's
                # properties will be updated if the component already exists,
                # and the the component will be created if it doesn't already
                # exist.
                ObjectMap(
                    {
                        'id': 'widgetbag-x7',
                        'relname': 'widgetbags',
                        'modname': 'ZenPacks.example.PackName.WidgetBag',
                        'shape': 'squiggle',
                    }
                ),

                # Components nested beneath other components can be updated
                # by using both compname to identify the relative path to the
                # parent component from its device, and relname to identify
                # the relationship on the parent component.
                ObjectMap(
                    {
                        'id': 'widget-z9',
                        'compname': 'widgetbags/widgetbag-x7',
                        'relname': 'widgets',
                        'modname': 'ZenPacks.example.PackName.Widget',
                        'color': 'magenta',
                    }
                ),

                # A special _add key can be added to an ObjectMap's data to
                # control whether or not the component will be added if it
                # doesn't already exist. The default value for _add is True
                # which will result in the component being created if it
                # doesn't already exist. Setting _add's value to False will
                # cause nothing to happen if the component doesn't already
                # exist. Sometimes this is desirable if you intend to have a
                # modeler plugin perform all component additions with your
                # datasource plugin only updating existing components.
                ObjectMap(
                    {
                        'id': 'widgetbag-x7',
                        'relname': 'widgetbags',
                        'modname': 'ZenPacks.example.PackName.WidgetBag',
                        'shape': 'crescent',
                        '_add': False,
                    }
                ),

                # A special _remove key can be added to an ObjectMap's data
                # to cause the identified component to be deleted. If a
                # matching component is not found, nothing will happen. The
                # default value for the _remove key is False. There's no
                # reason to set anything other than relname, optionally
                # compname, and id within data when setting _remove to True.
                # Matching is performed by joining compname/relname/id to
                # create a relative path to the component to be removed.
                ObjectMap(
                    {
                        'id': 'widgetbag-x7',
                        'relname': 'widgetbags',
                        'modname': 'ZenPacks.example.PackName.WidgetBag',
                        '_remove': True,
                    }
                ),

                # A RelationshipMap is used to update all of the components
                # in the specified relationship. A RelationshipMap must
                # supply an ObjectMap for each component in the relationship.
                # Any existing components that don't have a matching (by id)
                # ObjectMap within the RelationshipMap will be removed when
                # the RelationshipMap is applied.
                RelationshipMap(
                    relname='widgetbags',
                    modname='ZenPacks.zenoss.PackName.WidgetBag',
                    objmaps=[
                        ObjectMap(
                            {
                                'id': 'widgetbag-x7',
                                'shape': 'square'
                            }
                        ),
                        ObjectMap(
                            {
                                'id': 'widgetbag-y8',
                                'shape': 'hole'
                            }
                        ),
                    ]
                ),

                # As with ObjectMaps, compname can be used to update
                # relationships on components rather than relationships on
                # the device. These are often referred to as nested
                # components, or nested relationships.
                RelationshipMap(
                    compname='widgetbags/widgetbag-x7',
                    relname='widgets',
                    modname='ZenPacks.zenoss.PackName.Widget',
                    objmaps=[
                        ObjectMap(
                            {
                                'id': 'widget-z9',
                                'color': 'magenta'
                            }
                        ),
                        ObjectMap(
                            {
                                'id': 'widget-aa10',
                                'color': 'cyan'
                            }
                        ),
                    ]
                ),

                # Note that in this case because there are two "widgets"
                # relationships (one for each widgetbag), there must be two
                # RelationshipMaps to model them.
                RelationshipMap(
                    compname='widgetbags/widgetbag-y8',
                    relname='widgets',
                    modname='ZenPacks.zenoss.PackName.Widget',
                    objmaps=[
                        ObjectMap(
                            {
                                'id': 'widget-bb11',
                                'color': 'green'
                            }
                        ),
                        ObjectMap(
                            {
                                'id': 'widget-bb12',
                                'color': 'yellow'
                            }
                        ),
                    ]
                ),

                # All of the components in a relationship will be removed if
                # a RelationshipMap with an empty list of ObjectMaps
                # (objmaps) is supplied.
                RelationshipMap(
                    relname='widgetbags',
                    modname='ZenPacks.zenoss.PackName.WidgetBag',
                    objmaps=[]
                )
            ]
        }
```


Changes
---------------------

### 1.11.1 (2022-04-22)
* Fix cyclic references between PythonCollectionTask and plugins. (ZPS-6719)

### 1.11.0 (2019-07-02)
* Support extra datapoint tags in Zenoss Cloud. (ZPS-4587)
* Support publishing ad hoc metrics from plugins. (ZPS-4629)
* Provide better errors to collector when datamap application fails. (ZPS-5833)
* Avoid disabling plugins due to clock jumps by using monotonic clock.
* Allow testing of datasources with readable output. (ZEN-31038)

### 1.10.1 (2017-08-03)
* Fix RunningTimeoutError occurring instead of proper error. (ZPS-1755)

### 1.10.0
* Add "runningtimeout" option to zenpython. (ZPS-1675)
* Timeout datasources that stay running for triple their cycletime. (ZPS-1675)
* Add "timedOutTasks" metric to zenpython. (ZPS-1675)

### 1.9.0
* Add support of change the execution interval for a started task. (ZPS-70)
* Fix traceback when applying datamaps to deleted devices. (ZEN-24056)

### 1.8.1 (2016-07-19)
* Fix total collection failure when one bad config exists. (ZEN-23167)

### 1.8.0 (2016-06-22)
* Add 'twistedconcurrenthttp' option to zenpython
* Add ZenPacks.zenoss.PythonCollector.web.client.getPage() API
* Support optional _add property in naked ObjectMaps.
* Support optional _remove property in naked ObjectMaps.
* Document modeling from datasource plugins.

### 1.7.4 (2016-03-23)
* Increase default blockingtimeout from 5 to 30 seconds. (ZEN-22632)
* Enable all plugins if blockingtimeout is set to 0. (ZEN-22633)

### 1.7.3 (2015-11-25)
* Add "blockingtimeout" option to zenpython. (ZEN-19219)
* Change default "blockingwarning" from 30 to 3 seconds.

### 1.7.2 (2015-08-27)
* Add "blockingwarning" option to zenpython.
* Add detailed task state tracking to zenpython plugin execution.
* Add "percentBlocked" metric to zenpython.
* Restore compatibility with Zenoss 4.1.

### 1.7.1 (2015-07-30)
* Avoid a tight loop when writing metrics and events. (ZEN-18956)
* Switch back to epoll reactor. No select-dependent plugins left.

### 1.7.0 (2015-07-06)
* Fix datapoint format for Control Center metrics.
* Fix potential applyDataMaps traceback. (ZEN-17249)
* Add twistedthreadpoolsize configuration option to zenpython.
* Add optional startDelay property to PythonDataSourcePlugin.

### 1.6.4 (2015-03-30)
* Fix serviced datapoint format syntax. (ZEN-17255)

### 1.6.3 (2015-02-10)
* Revert to select reactor. Some plugins require it. (ZEN-16542)

### 1.6.2 (2015-01-27)
* Optimize datasource plugin loading. (ZEN-16344)
* Use epoll reactor to support >1024 descriptors. (ZEN-16164)

### 1.6.1 (2015-01-13)
* Add container Support for Zenoss 5X (Europa) services including RabbitMQ.

### 1.6.0 (2014-11-04)
* Provide PythonDataSourcePlugin instances access to hub services.
* Add --ignore and --collect options for zenpython.
* Handle Decimal performance values.
* Fix indexing bug when adding components with only an "id" property.

### 1.5.3 (2014-09-29)
* Switch to Zenoss 5 writeMetricWithMetadata() API.

### 1.5.2 (2014-09-25)
* Fix bug that causes device corruption on retried model transactions.
* Add support for Zenoss 5 writeMetric() API.

### 1.5.1 (2014-07-24)
* Fix bug in handling of long-typed values.

### 1.5.0 (2014-07-03)
* Fix application of maps in "run" mode.
* Support TALES evaluation of datapoint properties.
* Cleanup irrelevant errors when zenpython is forcefully stopped.
* Convert value timestamps to int for Zenoss 4.1 compatibility.
* Fix illegal update errors when attempting to write old values.
* Support collection of data for multiple timestamps in one interval.

### 1.4.0 (2014-04-02)
* Support callables in PythonDataSourcePlugin.proxy_attributes.

### 1.3.0 (2014-03-20)
* Optionally pass config into datasource plugins' __init__.
* Support ds_dp syntax for data['values'] keys.
* Support None return from datasource plugins' collect method.

### 1.2.0 (2013-11-25)
* Add cleanup hook for datasource plugins.

### 1.1.1 (2013-09-19)
* Improve incremental modeling support.

# 1.1.0 (2013-08-22)
* Support model updates from datasource plugins.
* Support incremental modeling.

### 1.0.2 (2013-07-29)
* Initial release.
