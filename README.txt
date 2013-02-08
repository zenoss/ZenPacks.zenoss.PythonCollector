Zenpacks.zenoss.PythonCollector

This zenpack provides a new daemon zenpython.  With this new daemon is a new DataSource 
which is a Python DataSource.

The Python DataSource can be extended in other zenpacks but it is here as a basis 
to inherit from.

The goal of this zenpack is to replicate the functionality of zencommand without
 requiring a subprocess call to the shell for commands.

This zenpack will require the creation of a python plugin to be used for
collection.

To use this zenpack create a new zenpack and add a directory called
datasource_plugins.  Really these plugins can exist most anywhere within the
python path of zope.  However some locations in the zenpack cause the plugin
to show up in menus that we dont want.  Also by using this module path in the
future the ui can be enhanced with a drop down list of available modules.

Below is an example module that exists in
ZenPacks.example.PythonCommand/ZenPacks/example/PythonCommand/datasource_plugins

The plugin is named EDSPlugin.py

This is what the plugin looks like.


from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import PythonDataSourcePlugin

class EDSPlugin(PythonDataSourcePlugin):
    "Extra configuration properties that exist on a device"
    proxy_attributes = ( 'zcommandusername', 'zcommandpassword' )

    "This is a classmethod that is executed in zenhub. The datasource
    and context parameters are the full objects."
    @classmethod
    def params(cls, datasource, context):
        pass

    "Method that actually does work.  This should return a twisted deferred and be
     asyncronous"
    def collect(self,config):
        pass

    "Method that if implemented would execute on the collect methods success"
    def onSuccess(self, results, config):
        pass

    "Method that if implemented would execute on the collect methods error if
     there was one"
    def onError(self, results, config):
        pass
    
    "Method that if implemented would execute on the collect methods success
     or failure"
    def onComplete(self, results, config):
        pass
   
    "Method that should already be implemented for you. 
     result should be a dictionary with two keys that are : events and values
     events is an array of event dictionaries with a device and severity.
     results is an array of tuples.  (component,value)
    def processResults(self,result):
    ...

    "Method that should already be implemented for you. 
     last way to handle any errors that may have occurred above.  
     Currently this just logs the result"
    def handleError(self,result):



Once the above plugin is created you can call it from a new python datasource.
Provide the full path to the class
ZenPacks.example.PythonCommand/ZenPacks/example/PythonCommand/datasource_plugins.EDSPlugin.EDSPlugin

see the screenshot in the screenshots dir for an example.

Create datapoints to store the results into.
