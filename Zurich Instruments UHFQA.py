#   @title      Zurich Instruments UHFQA instrument driver
#   @author     Christian Krizan
#   @date       2019-02-15
#   @version    v0.808

# Needed for other rudimentaries
from __future__ import print_function
import os
import re
import pydoc
import random
import sys
import numpy as np
import time
import textwrap
from BaseDriver import LabberDriver, Error, IdError

# Import ziPython from a relative path independent of system installation
# cmd_folder = os.path.realpath(os.path.abspath(os.path.split(inspect.getfile(inspect.currentframe()))[0]))
# if cmd_folder not in sys.path:
#     sys.path.insert(0, cmd_folder)

import zhinst.ziPython as ziPython
import zhinst.utils as ziUtils

# Actual class definition: class Driver(InstrumentDriver.InstrumentWorker):
class Driver(LabberDriver):


    """
###############################################################################
    SESSION SETUP AND SETTINGS
###############################################################################
    """


    # Instantiate a device connection using ziDAQServer
    def performOpen(self, options={}):
        """Perform the action of opening the instrument."""
        self.log('UHFQA MEAS START performOpen',level=30) # TODO MEAS

        # TODO Assert that LabOne is running on the personal computer

        self.dev_uppercase = 'DEV2346' # TODO this is a temporary fix; it is device-specific (which it should not be).
        self.dev = self.dev_uppercase.lower()

        # TODO transfer the self.dev_uppercase = self.comCfg.address from the
        # HDAWG driver, it's working.

        # Target goal (not implemented): connect to device using its DNS name.

        # Acquire device dictionary
        discov  = ziPython.ziDiscovery()
        props   = discov.get(discov.find(self.dev_uppercase))

        # Create an API session
        self.api_session = ziPython.ziDAQServer(
            props['serveraddress'], # Default: 'localhost'
            props['serverport'],    # Default: 8004
            props['apilevel']       # Default: 6
        )

        # Connect identified device to session
        self.api_session.connectDevice(
            self.dev_uppercase,
            props['interfaces'][0]
        )

        # Check if the API release version differs from the connected
        # data server's release version.
        ziUtils.api_server_version_check(self.api_session)

        # Acquire AWG module control, note that device ID is required.
        self.awgModule = self.api_session.awgModule()       # Acquire module.
        self.awgModule.set('awgModule/device', self.dev)    # Set device ID.

        # Instantiate the thread
        # Do not omit this step unless you know what you are doing.
        self.awgModule.execute()

        # Acquire the AWG data directory and its waveform directory.
        self.awg_data_dir = self.awgModule.getString('awgModule/directory')
        self.awg_waveform_dir = os.path.join(self.awg_data_dir, "awg", "waves")

        # Identify whether the waveform directory exists.
        if not os.path.isdir(self.awg_waveform_dir):
            raise Exception("Error: did not recognise AWG module waveform directory {}. Did you modify it?".format(self.awg_waveform_dir))

        # Acquire Scope Module control
        self.scopeModule = self.api_session.scopeModule()
        self.scopeModule.set('scopeModule/mode', 1)
        self.scopeModule.set('scopeModule/averager/weight', 1) # Disabled

        # TODO: for this particular UHFQA option, it is assumed there is only
        # one scope available, thus scope has been set as 0.
        scope = 0;
        self.scopeModule.subscribe('/' + self.dev + '/scopes/'+str(scope)+'/wave')

        # Instantiate the thread
        # Do not omit this step unless you know what you are doing.
        # self.scopeModule.execute()

        # Clear any/sporadically loaded waveform data
        self.loaded_waveform_1 = None
        self.loaded_waveform_2 = None

        # Generate a default AWG program
        # TODO: import the vectorWrite functionality from the HDAWG driver.
        self.generateLocalAwgProgram()

        # Generate a default padding value
        self.padding = 0

        # Generate a default state of AWG waveform playback
        self.AWG_plays_back_internally = 0

        # Generate a default averaging value (record amount to average)
        self.amountOfRecordsToAverage = 1

        # Generate default values for the two fetched channels
        # TODO: this depends on the amount of available channels right?
        self.acquired_data = [None, None]

        # Set up the data collection based on what channels are "activated"
        # Leave some time for the variables to take effect in the instruments.
        target_setting = 3
        channel_setting_timeout = 2.0 # seconds

        if self.getValue('ScopedVector2Enabled'):
            if not self.getValue('ScopedVector1Enabled'):
                target_setting = 2
        elif self.getValue('ScopedVector1Enabled'):
            target_setting = 1
        else:
            self.log('Severe Warning: no channels were enabled. Enabling both channel 1 and 2.',level=30)

        if self.api_session.getInt('/'+str(self.dev)+'/scopes/0/channel') != target_setting:
            self.api_session.setInt('/'+str(self.dev)+'/scopes/0/channel', target_setting)
            while self.api_session.getInt('/'+str(self.dev)+'/scopes/0/channel') != target_setting:
                time.sleep(0.1)
                self.api_session.sync()
                channel_setting_timeout -= 0.1
                if channel_setting_timeout <= 0:
                    raise Exception("Timed out when trying to activate the selected scope channels.") # TODO this should not be a generic exception

        self.log('UHFQA MEAS FINISHED performOpen',level=30)

        # TODO Go through all Exceptions and make them type specific, it's good practice.

    def performClose(self, bError=False, options={}):
        """Perform the close instrument connection operation"""
        # The try-exception is here since the API session might not have
        # been instantiated.
        try:
            # TODO find out what parts of the instrument should be shut down,
            # and shut them down.
            pass
        except UnboundLocalError:
            raise 'Could not close the device. There is likely no connection to the API.'


    def performSetValue(self, quant, value, sweepRate=0.0, options={}):
        """Perform the Set Value instrument operation. This function should
        return the actual value set by the instrument"""

        # Booleans
        # TODO how many scopes there are depends on installed options. Range should be 2.
        # TODO how many channels there are depends on installed options. Range should be something like 8
        # TODO single shot should be automatically set to zero when the scope triggers (Deprecated?)
        if quant.name in ['SigOut1On','SigOut2On'] + \
                         ['ImpedanceFifty1On','ImpedanceFifty2On'] + \
                         ['EnableScope'+str(x+1) for x in range(2)] + \
                         ['Force Scope '+str(x+1) for x in range(2)] + \
                         ['SingleShotScope'+str(x+1) for x in range(1)] + \
                         ['TriggerEnabledScope'+str(x+1) for x in range(1)] + \
                         ['Auto Threshold Input '+str(x+1) for x in range(4)] + \
                         ['Auto Range Input '+str(x+1) for x in range(2)] + \
                         ['ACSigIn'+str(x+1) for x in range(2)] + \
                         ['FiftyOhmSigIn'+str(x+1) for x in range(2)] + \
                         ['HysteresisMode'+str(x+1) for x in range(2)]:
            self.api_session.setInt(str(quant.get_cmd % self.dev), 1 if value else 0)

        # Simple floating points
        elif quant.name in ['TriggerVoltageScope'+str(x+1) for x in range(1)] + \
                           ['RangeSigIn'+str(x+1) for x in range(2)] + \
                           ['SampleLengthScope'+str(x+1) for x in range(1)] + \
                           ['ScalingSigIn'+str(x+1) for x in range(2)] + \
                           ['Oscillator'+str(x+1) for x in range(2)] + \
                           ['TriggerDelayScope'+str(x+1) for x in range(2)] + \
                           ['TriggerHoldoffScope'+str(x+1) for x in range(2)] + \
                           ['AmplitudeOutput'+str(x+1)+'AWG' for x in range(2)] + \
                           ['UserRegister'+str(x+1) for x in range(16)]:
            self.api_session.setDouble(str(quant.get_cmd % self.dev), float(value))

        # Combos
        # TODO SignalSourceChannel is specific and not generic, fix it.
        elif quant.name in ['TriggerFlankScope'+str(x+1) for x in range(1)] + \
                           ['SignalSourceChannel'+str(x+1)+'Scope1' for x in range(2)] + \
                           ['SamplingRateScope'+str(x+1) for x in range(1)] + \
                           ['TriggerSourceScope'+str(x+1) for x in range(1)] + \
                           ['TriggerFlankScope'+str(x+1) for x in range(1)] + \
                           ['DiffSigIn'+str(x+1) for x in range(2)] + \
                           ['ModeOutput'+str(x+1)+'AWG' for x in range(2)] + \
                           ['TriggerSourceAnalogue'+str(x+1)+'AWG' for x in range(2)] + \
                           ['TriggerSourceDigital'+str(x+1)+'AWG' for x in range(2)] + \
                           ['SlopeDigital'+str(x+1)+'AWG' for x in range(2)] + \
                           ['OutputSamplingRateAWG']:
            # Convert input to integer
            intValue = int(quant.getCmdStringFromValue(value))
            self.api_session.setInt(str(quant.get_cmd % self.dev), intValue)

        # Output signal range-related combos
        elif quant.name in ['RangeSigOut1']:
            # First, we must establish if we are in HiZ-mode or not
            if self.api_session.getInt('/'+self.dev+'/sigouts/0/imp50'):
                doubleValue = float(quant.getCmdStringFromValue(value))
            else:
                doubleValue = float(quant.getCmdStringFromValue(value))*2.0
            self.api_session.setDouble(str(quant.get_cmd % self.dev), doubleValue)
            self.local_awg_program = re.sub('const RSC = 1/[^;]+; // Range scaling', 'const RSC = 1/'+quant.getCmdStringFromValue(value)+'; // Range scaling', self.local_awg_program)

        elif quant.name in ['RangeSigOut2']:
            # First, we must establish if we are in HiZ-mode or not
            if self.api_session.getInt('/'+self.dev+'/sigouts/1/imp50'):
                doubleValue = float(quant.getCmdStringFromValue(value))
                # TODO channel 2?
            else:
                doubleValue = float(quant.getCmdStringFromValue(value))*2.0
                # TODO channel 2?
            self.api_session.setDouble(str(quant.get_cmd % self.dev), doubleValue)

        # Integer values that use floats for setting parameters in the server
        #elif quant.name in ['SampleLengthScope'+str(x+1) for x in range(1)]:
        #    self.api_session.setDouble(str(quant.get_cmd % self.dev), value*1.0)

        # awgModule-related Booleans
        elif quant.name in ['EnableAWG']:
            self.awgModule.set(str(quant.get_cmd), 1 if value else 0)

        # ... awgModule-related ANTI-Booleans
        elif quant.name in ['EnableRerunAWG']:
            self.api_session.setInt(str(quant.get_cmd % self.dev), 0 if value else 1)

        # DIO- and output DC-offset related floats
        elif quant.name in ['ManualThresholdRefTrigInput'+str(x+1) for x in range(4)] + \
                           ['OffsetSigOut'+str(x+1) for x in range(2)]:

            # Fix click-box incrementation being overridden by LabOne
            # TODO there should be some while-loop or similar for setting
            # and getting values in increments of 1.25% until the changes are
            # legal according to the server. (Deprecated?)

            #new_val = float(value)
            #old_val = self.api_session.getDouble(str(quant.get_cmd % self.dev))
            #if (old_val < new_val): # TODO while-loop
            #new_val = float(value)
            #new_value = new_val-new_val*1.05

            self.api_session.setDouble(str(quant.get_cmd % self.dev), float(value))
            value = self.api_session.getDouble(str(quant.get_cmd % self.dev))

        # Scope hysteresis-related doubles
        # TODO so what is the best way to force an update of another value? (in Labber?)
        elif quant.name in ['TriggerHysteresisScope'+str(x+1) for x in range(2)]:
            self.api_session.setInt('/'+self.dev+'/scopes/0/trighysteresis/mode', 0) # TODO this should fetch the current scope in question.
            self.api_session.setDouble(str(quant.get_cmd % self.dev), float(value))
            value = self.api_session.getDouble(str(quant.get_cmd % self.dev))
        elif quant.name in ['RelativeTriggerHysteresisScope'+str(x+1) for x in range(2)]:
            self.api_session.setInt('/'+self.dev+'/scopes/0/trighysteresis/mode', 1) # TODO this should fetch the current scope in question.
            self.api_session.setDouble(str(quant.get_cmd % self.dev), float(value)/100.0)
            value = self.api_session.getDouble(str(quant.get_cmd % self.dev))*100.0

        # Percentage-related floats
        elif quant.name in ['TriggerReferenceScope'+str(x+1) for x in range(2)]:
            self.api_session.setDouble(str(quant.get_cmd % self.dev), float(value)/100.0)

        # Factory reset etc.
        elif quant.name in ['I messed up...']:
            ziUtils.disable_everything(self.api_session, self.dev)

        # Compile and upload
        elif quant.name in ['Compile and upload']:
            self.compileAndUploadSourceString()

        # Insert Labber data vector into local program
        elif quant.name in ['Insert into program']:
            self.loadLabberVectorIntoProgram(0)
            self.loadLabberVectorIntoProgram(1)

        # Clear local AWG program
        elif quant.name in ['Clear local AWG program']:
            self.generateLocalAwgProgram()

        # Loaded vector playback rate related commands
        elif quant.name in ['LoadedVectorPlaybackRate'] + \
                           ['UseInternalVectorPlaybackRate']:
            value = self.localProgramPlayback(str(quant.get_cmd),value)

        # Commands related to amount of records to average every run
        elif quant.name in ['RecordAmountToAverage']:
            self.amountOfRecordsToAverage = int(value)

        # Simple signal generator-related commands
        elif quant.name in ['SimpleSigGenLoop','SimpleSigGenAwgPoints'] + \
                           ['SimpleSigGenAmplitude']:
            value = self.simpleSignalGenerator(str(quant.get_cmd),value)
        elif quant.name in ['SimpleSigGenWaveformType']:
            # Convert input to integer
            intValue = int(quant.getCmdStringFromValue(value))
            value = self.simpleSignalGenerator(str(quant.get_cmd), intValue)

        # Acquire data per scope
        elif quant.name in ['Acquire data using scope '+str(x+1) for x in range(2)]:
            pass
            # self.runScopeDataAcquisition(0,2.0) # TODO acquire time-out from the user (Labber instrument server)
            # self.setValue('ScopedVector1',self.acquired_data.get('wave')) # Set as Y-axis in a Labber vector


        # Final call check
        if self.isFinalCall(options):
            pass

            # self.loaded_waveform = self.getValueArray('LoadedVector')
            # np.savetxt("C:/Users/qtlab/Desktop/Vectordumps/Vectordump"+str(self.iteratorTODODEBUG)+".txt", self.loaded_waveform) # TODO DEBUG

            # if self.loaded_waveform is not None and len(self.loaded_waveform) > 0:
                # self.awgModule.set('awgModule/awg/enable', 0)
                # self.loadLabberVectorIntoProgram()

                # TODO no more file saving right?
                # TODO set up marker generation and triggering
                # TODO Make sure rerun AWG is off?

                # np.savetxt("C:/Users/qtlab/Desktop/Vectordumps/Vectordump"+str(self.iteratorTODODEBUG)+".txt", self.loaded_waveform) # TODO DEBUG
                # text_file = open("C:/Users/qtlab/Desktop/Vectordumps/Filedump"+str(self.iteratorTODODEBUG)+".txt", "w") # TODO DEBUG
                # text_file.write('Before compilation: \n'+self.local_awg_program) # TODO DEBUG # TODO DEBUG
                # self.compileAndUploadSourceString() # TODO DEBUG
                # self.api_session.sync() # TODO DEBUG
                # text_file.write('After compilation: \n'+self.local_awg_program) # TODO DEBUG
                # text_file.close() # TODO DEBUG

                # self.awgModule.set('awgModule/awg/enable', 1)
                # self.runScopeDataAcquisition(0,0.2) # TODO acquire time-out from the user (Labber instrument server)
                # self.setValue('ScopedVector1',self.acquired_data.get('wave')) # Set as Y-axis in a Labber vector

            # else:
                # np.savetxt("C:/Users/qtlab/Desktop/Vectordumps/NoRunAt"+str(self.iteratorTODODEBUG)+".txt", self.loaded_waveform) # TODO DEBUG


            # if self.iteratorTODODEBUG == 10: # TODO DEBUG
                # self.iteratorTODODEBUG = 0

                # Clean out any debris in LoadedVector
                # self.setValue('LoadedVector',[])

            # else:
                # self.iteratorTODODEBUG += 1

        return value

    def performGetValue(self, quant, options={}):
        """Perform the Get Value instrument operation. This function should
        return the actual value set by the instrument"""

        # Booleans
        # TODO how many scopes there are depends on installed options. Range should be 2.
        # TODO how many channels there are depends on installed options. Range should be something like 8
        # TODO single shot should be automatically set to zero when the scope triggers (Deprecated?)
        if quant.name in ['SigOut1On','SigOut2On'] + \
                         ['ImpedanceFifty1On','ImpedanceFifty2On'] + \
                         ['EnableScope'+str(x+1) for x in range(2)] + \
                         ['Force Scope '+str(x+1) for x in range(2)] + \
                         ['SingleShotScope'+str(x+1) for x in range(1)] + \
                         ['TriggerEnabledScope'+str(x+1) for x in range(1)] + \
                         ['ACSigIn'+str(x+1) for x in range(2)] + \
                         ['FiftyOhmSigIn'+str(x+1) for x in range(2)] + \
                         ['HysteresisMode'+str(x+1) for x in range(2)]:
            #value = self.api_session.getInt(str(quant.get_cmd % self.dev))
            return (self.api_session.getInt(str(quant.get_cmd % self.dev)) > 0)

        # Simple floating points
        elif quant.name in ['TriggerVoltageScope'+str(x+1) for x in range(1)] + \
                           ['AmplitudeOutput'+str(x+1)+'AWG' for x in range(2)] + \
                           ['RangeSigIn'+str(x+1) for x in range(2)] + \
                           ['ScalingSigIn'+str(x+1) for x in range(2)] + \
                           ['Oscillator'+str(x+1) for x in range(2)] + \
                           ['TriggerDelayScope'+str(x+1) for x in range(2)] + \
                           ['TriggerHoldoffScope'+str(x+1) for x in range(2)] + \
                           ['ManualThresholdRefTrigInput'+str(x+1) for x in range(4)] + \
                           ['OffsetSigOut'+str(x+1) for x in range(2)] + \
                           ['UserRegister'+str(x+1) for x in range(16)]:
            return self.api_session.getDouble(str(quant.get_cmd % self.dev))

        # Combos
        # TODO SignalSourceChannel is specific and not generic, fix it.
        # TODO get value for vertical channels is not working
        elif quant.name in ['TriggerFlankScope'+str(x+1) for x in range(1)] + \
                           ['SignalSourceChannel'+str(x+1)+'Scope1' for x in range(2)] + \
                           ['SamplingRateScope'+str(x+1) for x in range(1)] + \
                           ['TriggerSourceScope'+str(x+1) for x in range(1)] + \
                           ['TriggerFlankScope'+str(x+1) for x in range(1)] + \
                           ['DiffSigIn'+str(x+1) for x in range(2)] + \
                           ['ModeOutput'+str(x+1)+'AWG' for x in range(2)] + \
                           ['TriggerSourceAnalogue'+str(x+1)+'AWG' for x in range(2)] + \
                           ['TriggerSourceDigital'+str(x+1)+'AWG' for x in range(2)] + \
                           ['SlopeDigital'+str(x+1)+'AWG' for x in range(2)] + \
                           ['OutputSamplingRateAWG']:
            return quant.getValueFromCmdString(self.api_session.getInt(str(quant.get_cmd % self.dev)))


        # Output signal range-related combos
        elif quant.name in ['RangeSigOut1','RangeSigOut2']:
            if (self.api_session.getDouble(str(quant.get_cmd % self.dev)) - 0.200) < 0:
                return quant.getValueFromCmdString(0.075) # Then, we recieved a 'low' range
            else:
                return quant.getValueFromCmdString(0.75)

        # Integer values that use doubles for setting parameters in the server
        elif quant.name in ['SampleLengthScope'+str(x+1) for x in range(1)]:
            return int(self.api_session.getDouble(str(quant.get_cmd % self.dev)))

        # awgModule related Booleans
        elif quant.name in ['EnableAWG']:
            return self.awgModule.get(str(quant.get_cmd))

        # awgModule-related ANTI-Booleans
        elif quant.name in ['EnableRerunAWG']:
            return (self.api_session.getInt(str(quant.get_cmd % self.dev)) < 1)

        # Scope hysteresis-related doubles
        # TODO so what is the best way to force an update of another value? (in Labber?)
        elif quant.name in ['SimpleSigGenLoop']:
            return self.AWG_SSN_looping
        elif quant.name in ['TriggerHysteresisScope'+str(x+1) for x in range(2)]:
            #self.api_session.setInt('/'+self.dev+'/scopes/0/trighysteresis/mode', 0) # TODO this should fetch the current scope in question.
            return self.api_session.getDouble(str(quant.get_cmd % self.dev))
        elif quant.name in ['RelativeTriggerHysteresisScope'+str(x+1) for x in range(2)]:
            #self.api_session.setInt('/'+self.dev+'/scopes/0/trighysteresis/mode', 1) # TODO this should fetch the current scope in question.
            return self.api_session.getDouble(str(quant.get_cmd % self.dev))*100.0

        # Percentage-related floats
        elif quant.name in ['TriggerReferenceScope'+str(x+1) for x in range(2)]:
            return self.api_session.getDouble(str(quant.get_cmd % self.dev))*100.0

        # Loaded vector playback rate
        elif quant.name in ['LoadedVectorPlaybackRate']:
            return self.AWG_loaded_vector_playback_rate

        # Internal or external waveform playback source
        elif quant.name in ['UseInternalVectorPlaybackRate']:
            return self.AWG_plays_back_internally

        # Relative offset between channels 1 and 2
        # THIS FUNCTION IS DEPRECATED
        # elif quant.name in ['RelativePhaseOffset']:
        #    return self.AWG_relative_phase_channels_1_2

        # Commands related to amount of records to average every run
        elif quant.name in ['RecordAmountToAverage']:
            return self.amountOfRecordsToAverage*1.0

        # Simple signal generator
        elif quant.name in ['SimpleSigGenAwgPoints']:
            return self.AWG_SSG_no_points
        elif quant.name in ['SimpleSigGenAmplitude']:
            return self.AWG_SSG_amplitude
        elif quant.name in ['SimpleSigGenWaveformType']:
            return quant.getValueFromCmdString(self.AWG_SSG_waveform)

        # Acquire data from the scoped channels
        elif quant.name in ['ScopedVector1', 'ScopedVector2']:

            self.log('UHFQA MEAS START RATO: '+str(self.amountOfRecordsToAverage)+' Get scoped vector aka a measurment',level=30)
            # TODO Very important, does the /scopes/0/channel need to be configured (to for instance 3) in order to actually acquire data from channel 1 and 2 into the 'wave' dict?
            # (Deprecated?)

            self.log('A ScopedVector GET is running.',level=30)
            requested_channel = int(quant.name[-1])-1

            # Is the requested channel activated?
            if self.getValue(quant.name + 'Enabled'): #self.getValue('ScopedVector1Enabled')

                # The requested channel is activated. Is there already data
                # available for that channel or do we need to scope for it?
                if self.acquired_data[requested_channel] is None:

                    # There is no data available on that channel, a scope
                    # run must be performed to acquire it.

                    # Load value from other Labber-related instruments
                    # Also, ensure that the loaded waveforms are not NoneType
                    # when attempting the len operation below.

                    # Reset detection of duplicate waveform upload
                    update_channel_1 = 0
                    update_channel_2 = 0

                    if self.getValue('ScopedVector1Enabled'):
                        if not np.array_equal(self.loaded_waveform_1,self.getValueArray('LoadedVector1')):
                            update_channel_1 = 1
                            self.loaded_waveform_1 = self.getValueArray('LoadedVector1')
                    else:
                        self.loaded_waveform_1 = []
                    if self.getValue('ScopedVector2Enabled'):
                        if not np.array_equal(self.loaded_waveform_2,self.getValueArray('LoadedVector2')):
                            update_channel_2 = 1
                            self.loaded_waveform_2 = self.getValueArray('LoadedVector2')
                    else:
                        self.loaded_waveform_2 = []

                    # In case this is a get-run, the loaded vectors will be empty.
                    # Otherwise, we are clear to run the acquisition
                    if ((len(self.loaded_waveform_1) > 0) and self.getValue('ScopedVector1Enabled') and update_channel_1) or + \
                       ((len(self.loaded_waveform_2) > 0) and self.getValue('ScopedVector2Enabled') and update_channel_2):

                        self.awgModule.set('awgModule/awg/enable', 0)

                        if self.getValue('ScopedVector1Enabled'):
                            self.loadLabberVectorIntoProgram(0)
                        if self.getValue('ScopedVector2Enabled'):
                            self.loadLabberVectorIntoProgram(1)

                            # TODO this codelet sure does have optimisation potential

                        if self.AWG_plays_back_internally:
                            self.localProgramPlayback('setEditorPlayback',self.AWG_loaded_vector_playback_rate)

                        self.compileAndUploadSourceString()

                        self.api_session.sync()
                        self.awgModule.set('awgModule/awg/enable', 1)

                    else:
                        self.log("A loaded waveform had zero length. No scope acquisition was performed.",level=30)

                    if ((len(self.loaded_waveform_1) > 0) and self.getValue('ScopedVector1Enabled')) or ((len(self.loaded_waveform_2) > 0) and self.getValue('ScopedVector2Enabled')):
                        self.api_session.setInt('/' + self.dev + '/scopes/0/enable',1)
                        self.api_session.sync()

                        self.runScopeDataAcquisition(0) # TODO implement and acquire a time-out from the user (Labber instrument server)
                        self.log('A measurement has been completed.',level=30)
                    else:
                        # TODO hotfix
                        self.acquired_data[requested_channel] = 0


                    # Clear out the acquired data for the selected channel
                    # self.acquired_data[requested_channel] = None

                # Data is now available on the channel. Fetch it and mark
                # the channel as 'gotten' ie. None.

                # TODO What if the user sets the Scope sampling exponent ('time') after getting ScopedVector1 but before getting ScopeVector2?
                # This should be fixed with some self variable, which should only update when an actual scope session runs.

                scopeSamplingExponent = self.api_session.getInt('/'+self.dev+'/awgs/0/time')
                dt = 1/(1800000000/(2**(scopeSamplingExponent)))
                self.acquired_data_formatted = quant.getTraceDict(self.acquired_data[requested_channel], dt=dt)

                self.acquired_data[requested_channel] = None

            else:
                # The requested channel is not activated, return garbage.
                self.acquired_data_formatted = []

                scopeSamplingExponent = self.api_session.getInt('/'+self.dev+'/awgs/0/time')
                dt = 1/(1800000000/(2**(scopeSamplingExponent)))
                self.acquired_data_formatted = quant.getTraceDict([], dt=dt)

            self.log('UHFQA MEAS FINISHED RATO: '+str(self.amountOfRecordsToAverage)+'  Get scoped vector aka a measurment',level=30)
            return self.acquired_data_formatted

        return quant.getValue()



    """
###############################################################################
    SCOPE CONTROL
###############################################################################
    """



    # Acquire the current amount of scope module records
    def getScopeCurrentRecords(self):
        # TODO no error handling, for instance to see if scopeModule is active
        records = self.scopeModule.getInt('scopeModule/records')
        return records

    # Acquire a data set from the scope specifying duration time
    #def runScopeDataAcquisition(self,scope,timeout): # TODO
    def runScopeDataAcquisition(self,scope):

        # TODO A full acquisition is done during instrument bootup due to
        # this def, this should be investigated.

#        # Set up the data collection based on what channels are "activated"
#        if self.getValue('ScopedVector2Enabled'):
#            if self.getValue('ScopedVector1Enabled'):
#                self.api_session.setInt('/'+str(self.dev)+'/scopes/0/channel', 3)
#            else:
#                self.api_session.setInt('/'+str(self.dev)+'/scopes/0/channel', 2)
#        else:
#            if self.getValue('ScopedVector1Enabled'):
#                self.api_session.setInt('/'+str(self.dev)+'/scopes/0/channel', 1)
#            else:
#                self.log('Severe Warning: no channels were enabled. Enabling both channel 1 and 2.',level=30)
#                self.api_session.setInt('/'+str(self.dev)+'/scopes/0/channel', 3)

        # Create a wave nodepath. This is used to ensure that the data collected
        # stems from the correct module.
        wave_nodepath = '/' + self.dev + '/scopes/' + str(scope) + '/wave'

        # Maximum amount of tries for scoping
        maximum_amount_of_scope_tries = 3

        # Define the condition for success
        scope_run_successful = 0

        while not scope_run_successful:
            # We have initiated a scope run.

            # The first thing we do is to clear the scope history.
            self.scopeModule.set('scopeModule/clearhistory', 1)
            progress = 0
            records = 0

            # We then start the scope module, and enable the chosen scope.
            self.scopeModule.execute()
            self.api_session.setInt('/' + self.dev + '/scopes/' + str(scope) + '/enable', 1)

            # The data acquisition is now running.
            # It may terminate when we either have a sufficient amount of collected
            # records or when the scope reports its progress as completed.
            timeout = 0 # Hotfix TODO / CK

            while (records < self.amountOfRecordsToAverage or progress < 1.0) and (timeout < 60):
                time.sleep(0.025)
                records = self.scopeModule.getInt("scopeModule/records")
                progress = self.scopeModule.progress()[0]
                timeout += 0.025 # Hotfix TODO /CK

            # The data acquisition ran, we now shut off the module.
            self.api_session.setInt('/' + self.dev + '/scopes/' + str(scope) + '/enable', 0)
            self.scopeModule.finish()

            # Dump the data to the client
            data_read = self.scopeModule.read(True)

            # Was this a successful run?
            # There are two sufficient failure conditions:
            # If the wave nodepath is missing from the data (= no data acquired)
            # or if the amount of records were too few.
            if (wave_nodepath in data_read) and (records >= self.amountOfRecordsToAverage):

                # Successful. Break the loop.
                scope_run_successful = 1

            else:

                # Not successful. Decrease remaining trial count.
                # Restart the loop by not declaring the run completed.
                maximum_amount_of_scope_tries -= 1

                # If the trial amount expires, raise an error.
                if maximum_amount_of_scope_tries == 0:
                    raise 'Error: the subscribed data did not contain samples from '+self.dev+'\'s scope '+str(scope)+' in a reasonable amount of attempts.'

        # TODO Only operate on self.amountOfRecordsToAverage number of records
        # to save time and resources.

        acquired = data_read[wave_nodepath]

        # "Return" the acquired and averaged data.
        if self.getValue('ScopedVector1Enabled') or ( (not self.getValue('ScopedVector1Enabled')) and (self.getValue('ScopedVector2Enabled')) ):
            data = []

            for i, record in enumerate(acquired):
                wave = record[0]['wave']
                data.append(wave[0])

            self.acquired_data[0] = np.mean(data[:self.amountOfRecordsToAverage], axis=0)

        if self.getValue('ScopedVector2Enabled'):
            data = []

            for i, record in enumerate(acquired):
                wave = record[0]['wave']
                #data.append(wave[0])
                #self.log(wave,level=30) # TODO DEBUG
                data.append(wave[1])

            self.acquired_data[1] = np.mean(data[:self.amountOfRecordsToAverage], axis=0)

    """
###############################################################################
    AUXILIARY OUTPUT SETTINGS
###############################################################################
    """

    # Configure auxiliary outputs, set to manual mode
    def configureAuxOutputManual(self,signal,offset_in_volts,lower_limit_in_volts,upper_limit_in_volts):

        # TODO error handling such as incorrect signal selection and similar
        # TODO no error handling, which is rather bad for voltage settings
        self.api_session.setInt('/'+self.dev+'/auxouts/'+str(signal)+'/outputselect', -1)
        self.api_session.setDouble('/'+self.dev+'/auxouts/'+str(signal)+'/offset', offset_in_volts)
        self.api_session.setDouble('/'+self.dev+'/auxouts/'+str(signal)+'/limitlower', lower_limit_in_volts)
        self.api_session.setDouble('/'+self.dev+'/auxouts/'+str(signal)+'/limitupper', upper_limit_in_volts)

    # Configure auxiliary outputs, set to AWG mode
    def configureAuxOutputAwg(self,signal,channel_select,preoffset_in_nanovolts,scale_in_volts,offset_in_volts,lower_limit_in_volts,upper_limit_in_volts):

        nanovolt_value = preoffset_in_nanovolts * (10**(-9))

        # TODO: no error handling
        # TODO: look into self.api_session.set([stuff goes here]) for multi-setting parameters without calling the API several times.
        self.api_session.setInt('/'+self.dev+'/auxouts/'+str(signal)+'/outputselect', 4)
        self.api_session.setInt('/'+self.dev+'/auxouts/'+str(signal)+'/demodselect', channel_select)
        self.api_session.setDouble('/'+self.dev+'/auxouts/'+str(signal)+'/preoffset', nanovolt_value)

        actual_nanovolt_value = (self.api_session.getDouble('/'+self.dev+'/auxouts/'+str(signal)+'/preoffset'))*(10**9)
        print('Preoffset for signal '+str(signal)+' set to '+str(actual_nanovolt_value)+' volts.')

        self.api_session.setDouble('/'+self.dev+'/auxouts/'+str(signal)+'/scale', scale_in_volts)
        self.api_session.setDouble('/'+self.dev+'/auxouts/'+str(signal)+'/offset', offset_in_volts)
        self.api_session.setDouble('/'+self.dev+'/auxouts/'+str(signal)+'/limitlower', lower_limit_in_volts)
        self.api_session.setDouble('/'+self.dev+'/auxouts/'+str(signal)+'/limitupper', upper_limit_in_volts)
        self.api_session.sync()

    # Set all auxiliary outputs to their default settings
    def defaultAllAuxOutputs(self):
        for channels in [0,1,2,3]:
            self.api_session.setInt('/'+self.dev+'/auxouts/'+str(channels)+'/demodselect', channels)
            self.configureAuxOutputManual(channels,0,-10,10)

    # Force all auxiliary outputs to safe input voltages
    def forceAllAuxOutputsToSafeLevels(self):
        for channels in [0,1,2,3]:
            self.api_session.setDouble('/'+self.dev+'/auxouts/'+str(channels)+'/limitlower', -1.500)
            self.api_session.setDouble('/'+self.dev+'/auxouts/'+str(channels)+'/limitupper', 1.500)

            # TODO: missing control whether the limits are safe (get functions)

    """
###############################################################################
    REFERENCE TRIGGERS
###############################################################################
    """

    # Enable driving reference triggers
    def enableRefTriggerDrive(self,signal,state):
        # TODO no error handling
        self.api_session.setInt('/'+self.dev+'/triggers/out/'+signal+'/drive', state)

    # Set reference trigger impedances
    def setRefTriggerImpedance(self,signal_0_or_1,enable_50_ohm):
        # TODO no error handling
        self.api_session.setInt('/'+self.dev+'/triggers/in/'+str(signal_0_or_1)+'/imp50', enable_50_ohm)



    """
###############################################################################
    GENERATE LOCAL AWG PROGRAM
###############################################################################
    """

    def generateLocalAwgProgram(self):

        self.AWG_SSG_no_points = 2414
        self.AWG_SSG_amplitude = 1.0
        self.AWG_SSG_waveform = 1 # Sine
        self.AWG_SSN_looping = 1
        self.AWG_loaded_vector_playback_rate = 0
        #self.AWG_relative_phase_channels_1_2 = 0.0
        self.AWG_channel_1_is_playing = 0
        self.AWG_channel_2_is_playing = 0


        # TODO when only playing channel 2, how should the marker be set up?
        # Perhaps it would be a good idea to include some sort of marker on
        # channel 2?

        self.local_awg_program = textwrap.dedent("""\
const AWG_N = 2414;
const AWG_AMPL = 1.0;
const RSC = 1/0.75; // Range scaling
//var t = 0;

// Marker construction
//const marker_pos = 0;
//wave marker_left = marker(marker_pos,0);
//wave marker_right = marker(AWG_N-marker_pos,1);
//wave w_marker = join(marker_left,marker_right);

// Waveform definitions
//wave w0 = "wave0";
//wave w1 = gauss(AWG_N, AWG_N/2, AWG_N/20);
//wave w2;
//wave w3; // End of w3 definition
//wave w4; // End of w4 definition

// Waveform + marker construction and scaling
//wave w3_w_marker = RSC*w3;// + w_marker;
//wave w4_wo_marker = RSC*w4;

while(1){

//if (t == 0) {
waitDigTrigger(1,1);
setTrigger(1);
//playWave(w0);
//playWave(w1);
//playWave(w2);
//playWave(1,w3_w_marker); // Only channel 1 is playing
//playWave(2,w4_wo_marker); // Only channel 2 is playing
//playWave(1,w3_w_marker,2,w4_wo_marker); // Both channel 1 and 2 are playing
waitWave();
setTrigger(0);
//wait(10000);

//t = t + 1;
//} // End of t-swap

//if (t == 1) {
//wait(0);
//t = 0;
//} // End of t-reset




} // End of while-loop
            """
        )

#    def loadLabberVectorIntoProgram(self):
#        #self.loaded_waveform = self.getValueArray('LoadedVector')
#        self.local_awg_program = self.local_awg_program.replace('\n//wave w3;', '\nwave w3 = ;')
#        self.local_awg_program = self.local_awg_program.replace('\n//wave w3_w_marker', '\nwave w3_w_marker')
#        self.local_awg_program = self.local_awg_program.replace('\n//playWave(1,w3_w_marker)', '\nplayWave(1,w3_w_marker)')
#        self.local_awg_program = re.sub('wave w3 = [^;]+;', 'wave w3 = ;', self.local_awg_program)
#        self.local_awg_program = self.local_awg_program.replace('\nwave w3 = ', '\nwave w3 = vect('+','.join([str(x) for x in self.loaded_waveform_1])+')')

    def loadLabberVectorIntoProgram(self,channel):

        if channel == 0:
            self.AWG_channel_1_is_playing = 1
            self.local_awg_program = self.local_awg_program.replace('\n//wave w3;', '\nwave w3 = ;')
            self.local_awg_program = self.local_awg_program.replace('\n//wave w3_w_marker', '\nwave w3_w_marker')

            # Clean out the vector definition and refill.
            self.local_awg_program = re.sub('wave w3 = [^;]+;', 'wave w3 = ;', self.local_awg_program)
            self.local_awg_program = self.local_awg_program.replace('\nwave w3 = ', '\nwave w3 = vect('+','.join([str(x) for x in self.loaded_waveform_1])+')')

            if self.AWG_channel_2_is_playing:
                self.local_awg_program = self.local_awg_program.replace('\nplayWave(2,w4_wo_marker)', '\n//playWave(2,w4_wo_marker)')
                self.local_awg_program = self.local_awg_program.replace('\n//playWave(1,w3_w_marker,2,w4_wo_marker);', '\nplayWave(1,w3_w_marker,2,w4_wo_marker);')
            else:
                self.local_awg_program = self.local_awg_program.replace('\n//playWave(1,w3_w_marker)', '\nplayWave(1,w3_w_marker)')

        elif channel == 1:
            self.AWG_channel_2_is_playing = 1
            self.local_awg_program = self.local_awg_program.replace('\n//wave w4;', '\nwave w4 = ;')
            self.local_awg_program = self.local_awg_program.replace('\n//wave w4_wo_marker', '\nwave w4_wo_marker')

            # Clean out the vector definition and refill.
            self.local_awg_program = re.sub('wave w4 = [^;]+;', 'wave w4 = ;', self.local_awg_program)
            self.local_awg_program = self.local_awg_program.replace('\nwave w4 = ', '\nwave w4 = vect('+','.join([str(x) for x in self.loaded_waveform_2])+')')

            if self.AWG_channel_1_is_playing:
                self.local_awg_program = self.local_awg_program.replace('\nplayWave(1,w3_w_marker)', '\n//playWave(1,w3_w_marker)')
                self.local_awg_program = self.local_awg_program.replace('\n//playWave(1,w3_w_marker,2,w4_wo_marker);', '\nplayWave(1,w3_w_marker,2,w4_wo_marker);')
            else:
                self.local_awg_program = self.local_awg_program.replace('\n//playWave(2,w4_wo_marker)', '\nplayWave(2,w4_wo_marker)')

    def appendToLocalAwgProgramFromCsv(self):
        print('Error')

    def localProgramPlayback(self, command, value):

        # TODO this is a false setting, there should be some self-based
        # variable keeping track of the old value set for set_value,
        # and return that in case the new value is illegal.
        set_value = value

        # Request playback rate to be set
        if command == 'setEditorPlayback':

            # Does the user want to disable vector playback?
            if value <= 0:
                # The user has demanded the playback to be disabled
                set_value = 0.0

                # Undo the previous wait clauses
                self.local_awg_program = self.local_awg_program.replace('\nvar t = 0;', '\n//var t = 0;')
                self.local_awg_program = self.local_awg_program.replace('\nif (t == 0) {', '\n//if (t == 0) {')
                self.local_awg_program = self.local_awg_program.replace('\nt = t + 1;', '\n//t = t + 1;')
                self.local_awg_program = self.local_awg_program.replace('\n} // End of t-swap', '\n//} // End of t-swap')
                self.local_awg_program = re.sub('\nif \(t == 1\) {\nwait\(.*\);\nt = 0;\n} \/\/ End of t-reset','\n//if (t == 1) {\n//wait(0);\n//t = 0;\n//} // End of t-reset',self.local_awg_program)
                self.local_awg_program = self.local_awg_program.replace('\nif (t == 1) {\nwait(0);\nt = 0;\n} // End of t-reset', '\n//if (t == 1) {\n//wait(0);\n//t = 0;\n//} // End of t-reset')

                # Is there any padding that need removal?
                if self.padding > 0:
                    if ('= vect(' in self.local_awg_program) :
                        for x in range(self.padding):
                            self.local_awg_program = self.local_awg_program.replace(',0.0); // End of w3 definition','); // End of w3 definition')
                    else:
                        self.log("Interestingly, there were padded zeroes to remove but the local program did not contain a loaded vector. You should look into this.")

                    # Clear out self.padding
                    self.padding = 0

                # TODO: Experiments have shown that the padding is no longer working since version 0.75,
                # A revert of this function is in order although put on hold until the external
                # triggering function from the HDAWG is up and running.


            else:
                # The user has demanded a new value to be set
                set_value = value

                """
                Algorithm:
                - Acquire length of the current loadedvector
                - Assert loadedvector is not blank, in that case do nothing
                - Fetch the current AWG playback rate, in Sa/s
                - len(vector)/f_s = seconds_for_playing_w3

                (- Take set_value)
                - ASSERT set_value - seconds_for_playing_w3 >= 0 aka. the w3 vector
                    is not longer than the requested playback rate.
                - delay_time_needed = sample_playback_interval - seconds_for_playing_w3

                How many ticks of delay at 225 MHz?
                - delay_time_needed * 225000000 = no_of_ticks_needed

                Pls. get a finer resolution than 4,44 ns:
                - no_of_ticks_needed % 1 = rest
                - padding = rest / (225000000 * f_s)       # seconds needed / sample playback rate

                Fix local program:
                - APPEND padding to w3
                - REPLACE the wait with wait(no_of_ticks_needed)


                """

                # Get the loaded vector and its length
                vector = self.getValueArray('LoadedVector1')
                current_vector_length = len(vector)

                # Assert that it is a valid vector
                if vector is not None and current_vector_length > 0:

                    # The vector is valid, let the system know that internal
                    # playback is used.
                    self.AWG_plays_back_internally = 1

                    # Get current AWG playback rate
                    awgPlaybackExponent = self.api_session.getInt('/'+self.dev+'/awgs/0/time')
                    awgPlaybackRate = 1800000000/(2**(awgPlaybackExponent))

                    # How many seconds are required to play w3?
                    seconds_for_playing_w3 = current_vector_length / awgPlaybackRate

                    # Establish delay needed and ensure there is time for a pause
                    delay_time_needed = set_value - seconds_for_playing_w3
                    assert delay_time_needed >= 0, "Insufficient time left for waveform playback" # TODO this clause is identified as a potential issue with the hard-coding of -9 to required_wait_cycles
                    no_of_ticks_needed = delay_time_needed * 225000000 # Internal delay clock

                    # Establish what number to put in the wait clause in the local AWG program
                    required_wait_cycles = int(no_of_ticks_needed)-8 # TODO this used to be 9, se above comment (assert delay_time_needed blabla)

                    # TODO the required wait cycles should lessen with the amount
                    # of cycles required to run the actual program. It is hard-coded above

                    # Insert wait clause
                    self.local_awg_program = self.local_awg_program.replace('\n//var t = 0;', '\nvar t = 0;')
                    self.local_awg_program = self.local_awg_program.replace('\n//if (t == 0) {', '\nif (t == 0) {')
                    self.local_awg_program = self.local_awg_program.replace('\n//t = t + 1;', '\nt = t + 1;')
                    self.local_awg_program = self.local_awg_program.replace('\n//} // End of t-swap', '\n} // End of t-swap')
                    self.local_awg_program = self.local_awg_program.replace('\n//if (t == 1) {\n//wait(0);\n//t = 0;\n//} // End of t-reset', '\nif (t == 1) {\nwait('+str(required_wait_cycles)+');\nt = 0;\n} // End of t-reset')

                    # In case we were merely updating an old setting:
                    self.local_awg_program = re.sub('\nif \(t == 1\) {\nwait\(.*\);\nt = 0;\n} \/\/ End of t-reset','\nif (t == 1) {\nwait('+str(required_wait_cycles)+');\nt = 0;\n} // End of t-reset',self.local_awg_program)

                    # Do we also require padding?
                    rest = no_of_ticks_needed % 1.0
                    if (rest > 0) :

                        self.log("The rest exists. The amount of ticks needed is not an integer. The rest was "+str(rest),level=30) # TODO DEBUG

                        maximum_possible_resolution = 1/awgPlaybackRate

                        self.log("The maximum possible resolution was "+str(maximum_possible_resolution),level=30) # TODO DEBUG
                        self.log("The AWG playback rate was set to "+str(awgPlaybackRate),level=30) # TODO DEBUG

                        # Can the rest even be represented at the maximum resolution?
                        if (rest/225000000 > maximum_possible_resolution):

                            self.padding = int((rest / 225000000)*awgPlaybackRate) # Time needed / Playback rate

                            self.log("The rest evaluated vs the final resolution as representable. The padding is now "+str(self.padding),level=30) # TODO DEBUG

                            # Append 'padding' amount of zeroes to the w3 vector
                            zero_vector_string = [str(0.0) for x in range(self.padding)]

                            # Keep in mind that if the padding amount is 0, a '[]' will be inserted into the vector inside the local program.
                            # This will however never happen due to the if rest > maximum_possible_resolution above.

                            self.local_awg_program = self.local_awg_program.replace('); // End of w3 definition', ','+(((str(zero_vector_string).replace(' ','')).replace('\'','')).replace('[','')).replace(']','') + '); // End of w3 definition')

                            # TODO Insertion of padding into both vectors must be done in a better way. Imagine if this is done in the wrong order. Or if one vector is deactivated, and the padding then overwritten?

                        # TODO
                        #self.local_awg_program = re.sub('wave w3 = [^;]+;', 'wave w3 = ;', self.local_awg_program)
                        #self.local_awg_program = self.local_awg_program.replace('\nwave w3 = ', '\nwave w3 = vect('+','.join([str(x) for x in self.loaded_waveform])+')')

                    else:
                        # We do not require padding.
                        self.padding = 0

            self.AWG_loaded_vector_playback_rate = set_value

        elif command == 'useInternalPlayback':
            self.AWG_plays_back_internally = value
            set_value = value # TODO Aren't there too many set_value assignments in this function like everywhere?

        return set_value

    # TODO this entire comment blob is likely not to be implemented and should be removed
    # Enable disable AWG Playback rate
    #def enablelocalProgramPlayback():
        # TODO: insert enable/disable box into Labber,
        # check if the loaded vector is a valid vector
        #   if it is, then insert this into the program:

                # self.local_awg_program = self.local_awg_program.replace('\n//var t = 0;', '\nvar t = 0;')
                # self.local_awg_program = self.local_awg_program.replace('\n//if (t == 0) {', '\nif (t == 0) {')
                # self.local_awg_program = self.local_awg_program.replace('\n//t = t + 1;', '\nt = t + 1;')
                # self.local_awg_program = self.local_awg_program.replace('\n//} // End of t-swap', '\n} // End of t-swap')
                # TODO Add some comment after the wait clause to designate it better in the regex, and replace whatever is inside it with the appropriate value
                # self.local_awg_program = self.local_awg_program.replace('\n//if (t == 1) {\n//wait(0);\n//t = 0;\n//} // End of t-reset', '\nif (t == 1) {\nwait('+str(required_wait_cycles)+');\nt = 0;\n} // End of t-reset')

                # Do we also require padding?
                # rest = no_of_ticks_needed % 1.0
                # if (rest > 0) :
                    # maximum_possible_resolution = 1/awgPlaybackRate
                    # padding = (rest / 225000000)/awgPlaybackRate # Time needed / Playback rate

                    # Append 'padding' amount of zeroes to the w3 vector
                    # zero_vector_string = [",0.0" for x in range(padding)]
                    # self.local_awg_program = self.local_awg_program.replace('); // End of w3 definition', zero_vector_string + '); // End of w3 definition')

                    # TODO
                    # #self.local_awg_program = re.sub('wave w3 = [^;]+;', 'wave w3 = ;', self.local_awg_program)
                    # #self.local_awg_program = self.local_awg_program.replace('\nwave w3 = ', '\nwave w3 = vect('+','.join([str(x) for x in self.loaded_waveform])+')')


        # Make sure to update the bool appropriately in accordance with what
        # Labber expects.

        # On disable

    #    pass


    # Simple signal generator function
    def simpleSignalGenerator(self, command, value):
        # TODO some assertion is needed in order to default on something
        # unexpected from the ini-file

        # Request "seamless" looping
        if command == 'loop':
            set_value = int(value)
            if set_value:
                # Loop
                self.local_awg_program = self.local_awg_program.replace('\n//while(1){', '\nwhile(1){')
                self.local_awg_program = self.local_awg_program.replace('\n//} // End of while-loop', '\n} // End of while-loop')
                self.AWG_SSN_looping = 1
            else:
                # Unloop
                self.local_awg_program = self.local_awg_program.replace('\nwhile(1){', '\n//while(1){')
                self.local_awg_program = self.local_awg_program.replace('\n} // End of while-loop', '\n//} // End of while-loop')
                self.AWG_SSN_looping = 0

        # Set the number of AWG points in the waveform
        elif command == 'awgPoints':
            set_value = int(value)
            self.local_awg_program = self.local_awg_program.replace('\nconst AWG_N = '+str(self.AWG_SSG_no_points), '\nconst AWG_N = '+str(set_value))
            self.AWG_SSG_no_points = set_value

        # Define the waveform that is to be played back
        elif command == 'wave':
            # A waveform command was chosen from a combination box, simply
            # set that box to what it is supposed to be.
            set_value = value
            if value == 1: # Sine wave # TODO non-optimised in terms of upload speed
                #self.waveform_1 = 0.5*np.sin(np.linspace(0, random.randint(1,10)*np.pi, self.AWG_simple_sig_gen))
                # TODO phase offset, number of periods
                #self.local_awg_program = self.local_awg_program.replace('\n//wave w2', '\nwave w2 = sine(AWG_N,AWG_AMPL,0,1)')

                # TODO there should be something in the way of tickboxes for
                # controlling what waves get played back
                # Make sure there are default waveforms to play then.
                #self.local_awg_program = self.local_awg_program.replace('\n//playWave(w2)', '\nplayWave(w2)')
                self.AWG_SSG_waveform = set_value
            elif value == 2:
                # TODO square wave
                self.AWG_SSG_waveform = set_value
            elif value == 3:
                # TODO triangular wave
                self.AWG_SSG_waveform = set_value

        elif command == 'amplitude':
            set_value = float(value)
            self.local_awg_program = self.local_awg_program.replace('\nconst AWG_AMPL = '+str(self.AWG_SSG_amplitude), '\nconst AWG_AMPL = '+str(set_value))
            self.AWG_SSG_amplitude = set_value

        return set_value

    """
###############################################################################
    COMPILE AND/OR UPLOAD WAVEFORM DATA
###############################################################################
    """

    # Blast the device memory
    def blastMemory(self):
        print('Error')


    # TODO The function injectMemory is defective and should be replaced entirely
    # with the HDAWG-method.

    # Inject waveform data into the device mnemonically
    def injectMemory(self, target_waveform_index, waveform_data_to_inject):
        # For the transferred array, floating-point (-1.0...+1.0) and
        # 16 bit signed integers are allowed (-32768 ... +32767).
        # Dual-channel waves require interleaving is required.

        # Index = waveform in the sequencer program that will be replaced
        # with the data in awgs/X/waveform/data.

        # N = total number of waveforms
        # M>0 = number of waveforms defined per CSV file
        # Index = 0,...,M-1 for all CSV-defined waveforms sorted alphabetically by filename,
        # M,...,N-1 in the order that the waveforms are defined in the sequencer program.

        # So for instance if there are no CSV-defined waveforms, index = 2
        # would correspond to the third waveform given in the sequencer program.

        self.waven = np.sinc(np.linspace(-6*np.pi, 6*np.pi, 2000))
        #index = 3
        self.api_session.setInt('/' + self.dev + '/awgs/0/waveform/index', target_waveform_index)
        self.api_session.sync()

        self.api_session.vectorWrite('/' + self.dev + '/awgs/0/waveform/data', self.waven)


    # Engage the AWG compiler and upload source string to the device.
    def compileAndUploadSourceString(self):

        self.log('UHFQA MEAS START RATO: '+str(self.amountOfRecordsToAverage)+'  compile',level=30)

        # Note: compiler/start needs only to be set if explicitly compiling
        # from source file.

        # As the compilation progress halts AWG playback, we fetch the current
        # user-set status of it. We acquire a dictionary of dictionaries.
        current_AWG_playback_status = self.awgModule.get('awgModule/awg/enable')

        # This step is done seemingly because the AWG returns a 1 when polled
        # briefly after uploading even though it is clearly not playing.
        self.awgModule.set('awgModule/awg/enable',0)

        # Check if a specific source string has been requested
        # TODO removed 'Default' due to errors
        program = self.local_awg_program

        # Transfer the source string to the compiler.
        self.awgModule.set('awgModule/compiler/sourcestring', program)

        # Compiling process has initialised.
        while self.awgModule.getInt('awgModule/compiler/status') == -1:
            print('Compiling...')
            time.sleep(0.1)

        # Compilation failure.
        if self.awgModule.getInt('awgModule/compiler/status') == 1:
            raise Exception(self.awgModule.getString('awgModule/compiler/statusstring'))

        # Compilation successful.
        if self.awgModule.getInt('awgModule/compiler/status') == 0:
            print("Compilation fully successful, will upload the program to the instrument.")
            self.log("Compilation fully successful, will upload the program to the instrument.", level=30)

        # Compilation successful with warnings.
        if self.awgModule.getInt('awgModule/compiler/status') == 2:
            print("Compilation successful with warnings, will upload the program to the instrument.")
            self.log("Compilation successful with warnings, will upload the program to the instrument.",level=30)
            self.log("Compiler warning: " + self.awgModule.getString('awgModule/compiler/statusstring'),level=30)
            # print("Compiler warning: ", self.awgModule.getString('awgModule/compiler/statusstring'))
            # raise Exception(self.awgModule.getString('awgModule/compiler/statusstring'))

        self.log('UHFQA MEAS FINISHED RATO: '+str(self.amountOfRecordsToAverage)+'  compile',level=30)
        self.log('UHFQA MEAS START RATO: '+str(self.amountOfRecordsToAverage)+'  upload',level=30)

        # Initiate upload process.
        time.sleep(0.2)
        i = 0

        # elf/status provides information whether the upload is succeeding or not.
        while (self.awgModule.getDouble('awgModule/progress') < 1.0) and (self.awgModule.getInt('awgModule/elf/status') != 1):
            print("{} awgModule/progress: {:.0f}%".format(i, self.awgModule.getDouble('awgModule/progress')*100.0))
            time.sleep(0.5)
            i += 1

        if self.awgModule.getInt('awgModule/elf/status') == 0:
            print("Upload to the instrument successful.")

        if self.awgModule.getInt('awgModule/elf/status') == 1:
            raise Exception("Upload to the instrument failed at {:.2f}".format(self.awgModule.getDouble('awgModule/progress')))

        # If the device was playing before, enable playback again.
        if ((current_AWG_playback_status.get('awg')).get('enable')[0]) == 1:
            i = 0
            while ((self.awgModule.get('awgModule/awg/enable')).get('awg')).get('enable')[0] != 1:
                time.sleep(0.1)
                self.awgModule.set('awgModule/awg/enable',1)
                if i == 1:
                    print('The AWG module is very slow to respond.')
                i += 1;
        self.log('UHFQA MEAS FINISHED RATO: '+str(self.amountOfRecordsToAverage)+'  upload',level=30)


    """
###############################################################################
    DEBUG AND TESTING FUNCTIONALITY
###############################################################################
    """

    # Put a random number in user register X
    def setRandomIntegerIntoUserReg(self,from_integer,to_integer,register):
        not_ok = 1;

        while not_ok == 1 :
            new_var = random.randint(from_integer, to_integer)/1.0
            old_var = self.api_session.getDouble('/'+self.dev+'/awgs/0/userregs/'+str(register))
            #print(str(new_var))
            if (new_var != old_var) :
                not_ok = 0

        self.api_session.setDouble('/'+self.dev+'/awgs/0/userregs/'+str(register), new_var)

    # Dump a particular help prompt to disk
    def dumpHelpToFile(self,requested_help_to_dump):
        f = open("C:/Users/qtlab/Desktop/Helpdump.txt", "w")
        sys.stdout = f
        pydoc.help(requested_help_to_dump)
        f.close()
        sys.stdout = sys.__stdout__
        return

    # Preset debug setup
    def runConfigForExample(self):

        out_channel = 0
        out_mixer_channel = 3
        in_channel = 0
        osc_index = 0
        awg_channel = 0
        frequency = 1e6
        amplitude = 1.0

        self.cleanSlate()
        exp_setting = [
            ['/%s/sigins/%d/imp50'             % (self.dev, in_channel), 1],
            ['/%s/sigins/%d/ac'                % (self.dev, in_channel), 0],
            ['/%s/sigins/%d/diff'              % (self.dev, in_channel), 0],
            ['/%s/sigins/%d/range'             % (self.dev, in_channel), 1],
            ['/%s/oscs/%d/freq'                % (self.dev, osc_index), frequency],
            ['/%s/sigouts/%d/on'               % (self.dev, out_channel), 1],
            ['/%s/sigouts/%d/range'            % (self.dev, out_channel), 1],
            ['/%s/sigouts/%d/enables/%d'       % (self.dev, out_channel, out_mixer_channel), 1],
            ['/%s/sigouts/%d/amplitudes/*'     % (self.dev, out_channel), 0.],
            ['/%s/awgs/0/outputs/%d/amplitude' % (self.dev, awg_channel), amplitude],
            ['/%s/awgs/0/outputs/0/mode'       % self.dev, 0],
            ['/%s/awgs/0/time'                 % self.dev, 0],
            ['/%s/awgs/0/userregs/0'           % self.dev, 0]
        ]
        self.api_session.set(exp_setting)
        self.api_session.sync()


    # Compare specified and acquired data
    def compareAcquiredData(self):

        #f_s = 1.8e9  # sampling rate of scope and AWG
        #for n in range(0, len(data['channelenable'])):
        #    p = data['channelenable'][n]
        #    if p:
        #        y_measured = data['wave'][n]
        #        x_measured = np.arange(-data['totalsamples'], 0)*data['dt'] + \
        #(data['timestamp'] - data['triggertimestamp'])/f_s

#        # Compare expected and measured signal
#        full_scale = 0.75
#        y_expected = np.concatenate((waveform_0, waveform_1, waveform_2, waveform_3))*full_scale*amplitude
#        x_expected = np.linspace(0, 4*AWG_N/f_s, 4*AWG_N)
#
#        # Correlate measured and expected signal
#        corr_meas_expect = np.correlate(y_measured, y_expected)
#        index_match = np.argmax(corr_meas_expect)
#
#        if do_plot:
#            # The shift between measured and expected signal depends among other things on cable length.
#            # We simply determine the shift experimentally and then plot the signals with an according correction
#            # on the horizontal axis.
#            x_shift = index_match/f_s - trigreference*(x_measured[-1] - x_measured[0]) + trigdelay
#            import matplotlib.pyplot as plt
#            print('Plotting the expected and measured AWG signal.')
#            x_unit = 1e-9
#            plt.figure(1)
#            plt.clf()
#            plt.title('Measured and expected AWG Signals')
#            plt.plot(x_measured/x_unit, y_measured, label='measured')
#            plt.plot((x_expected + x_shift)/x_unit, y_expected, label='expected')
#            plt.grid(True)
#            plt.autoscale(axis='x', tight=True)
#            plt.legend(loc='upper left')
#            plt.xlabel('Time, relative to trigger (ns)')
#            plt.ylabel('Voltage (V)')
#            plt.draw()
#            plt.show()
#
#        # Normalize the correlation coefficient by the two waveforms and check they
#        # agree to 95%.
#        norm_correlation_coeff = corr_meas_expect[index_match]/np.sqrt(sum(y_measured**2)*sum(y_expected**2))
#        assert norm_correlation_coeff > 0.95, \
#            ("Detected a disagreement between the measured and expected signals, "
#             "normalized correlation coefficient: {}.".format(norm_correlation_coeff))
#        print("Measured and expected signals agree, normalized correlation coefficient: ",
#              norm_correlation_coeff, ".", sep="")
#        return data_read
        pass
