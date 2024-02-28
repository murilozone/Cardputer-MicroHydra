



"""

VERSION: 0.7

CHANGES:
    Adjusted battery level detection, improved launcher sort method,
    added apps folders to import path,
    added ability to jump to alphabetical location in apps list,
    added new fbuf-based display driver to lib

This program is designed to be used in conjunction with the "apploader.py" program, to select and launch MPy apps for the Cardputer.

The basic app loading logic works like this:

 - apploader reads reset cause and RTC.memory to determine which app to launch
 - apploader launches 'launcher.py' when hard reset, or when RTC.memory is blank
 - launcher scans app directories on flash and SDCard to find apps
 - launcher shows list of apps, allows user to select one
 - launcher stores path to app in RTC.memory, and soft-resets the device
 - apploader reads RTC.memory to find path of app to load
 - apploader clears the RTC.memory, and imports app at the given path
 - app at given path now has control of device.
 - pressing the reset button will relaunch the launcher program, and so will calling machine.reset() from the app. 



This approach was chosen to reduce the chance of conflicts or memory errors when switching apps.
Because MicroPython completely resets between apps, the only "wasted" ram from the app switching process will be from launcher.py



"""



#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Constants: ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


max_wifi_attemps = const(1000)
max_ntp_attemps = const(10)

#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Global: ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
# these larger objects are created here to reserve their memory asap
import gc
gc.collect()

import network, ntptime
try:
    nic = network.WLAN(network.STA_IF)
except RuntimeError as e:
    try:
        nic = network.WLAN(network.STA_IF)
    except RuntimeError as e:
        nic = None
        print("Wifi WLAN object couldnt be created. Gave this error:",e)
gc.collect()

from lib import beeper
from lib.mhconfig import Config
beep = beeper.Beeper()
config = Config()

from lib import st7789fbuf as st7789
import machine
#init driver for the graphics
tft = st7789.ST7789(
    machine.SPI(1, baudrate=40000000, sck=machine.Pin(36), mosi=machine.Pin(35), miso=None),
    135,
    240,
    reset=machine.Pin(33, machine.Pin.OUT),
    cs=machine.Pin(37, machine.Pin.OUT),
    dc=machine.Pin(34, machine.Pin.OUT),
    backlight=machine.Pin(38, machine.Pin.OUT),
    rotation=1,
    color_order=st7789.BGR,
    custom_framebufs =((0,0,240,35),(0,35,240,38),(0,73,240,39),(0,112,240,23))
    ) # 	buf_idx: 0(status bar), 1(app icons), 2(app text), 3(scroll bar)



# global vars for animation
scroll_factor = 0.0

prev_text_scroll_position = 0
text_scroll_position = 0
text_drawing = True

prev_icon_scroll_position = 0
icon_scroll_position = 0
icon_drawing = True

# control the show() commands
buf_0_modified = True
buf_1_modified = True
buf_2_modified = True
buf_3_modified = True

# app selector
app_selector_index = 0
prev_selector_index = 0
app_names = []
app_paths = []

clock_minute_drawn = -1

gc.collect()
from font import vga2_16x32 as font
from launcher.icons import icons, battery
from lib import keyboard
import time, os
gc.collect()
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Finding Apps ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def scan_apps(sd):
    # first we need a list of apps located on the flash or SDCard
    gc.collect()
    main_directory = os.listdir("/")
    
    # if the sd card is not mounted, we need to mount it.
    if "sd" not in main_directory:
        try:
            sd = machine.SDCard(slot=2, sck=machine.Pin(40), miso=machine.Pin(39), mosi=machine.Pin(14), cs=machine.Pin(12))
        except OSError as e:
            print(e)
            print("SDCard couldn't be initialized. This might be because it was already initialized and not properly deinitialized.")
            try:
                sd.deinit()
            except:
                print("Couldn't deinitialize SDCard")
        
        if sd != None: # error above can lead to none type here
            try:
                os.mount(sd, '/sd')
            except OSError as e:
                print(e)
                print("Could not mount SDCard.")
            except NameError as e:
                print(e)
                print("SDCard not mounted")
            
        main_directory = os.listdir("/")

    sd_directory = []
    if "sd" in main_directory:
        sd_directory = os.listdir("/sd")

    # if the apps folder does not exist, create it.
    if "apps" not in main_directory:
        os.mkdir("/apps")
        main_directory = os.listdir("/")
        
    # do the same for the sdcard apps directory
    if "apps" not in sd_directory and "sd" in main_directory:
        os.mkdir("/sd/apps")
        sd_directory = os.listdir("/sd")

    # if everything above worked, sdcard should be mounted (if available), and both app directories should exist. now look inside to find our apps:
    main_app_list = os.listdir("/apps")
    sd_app_list = []

    if "sd" in main_directory:
        try:
            sd_app_list = os.listdir("/sd/apps")
        except OSError as e:
            print(e)
            print("SDCard mounted but cant be opened; assuming it's been removed. Unmounting /sd.")
            os.umount('/sd')

    # now lets collect some separate app names and locations
    app_names = []
    app_paths = {}

    for entry in main_app_list:
        if entry.endswith(".py"):
            this_name = entry[:-3]
            
            # the purpose of this check is to prevent dealing with duplicated apps.
            # if multiple apps share the same name, then we will simply use the app found most recently. 
            if this_name not in app_names:
                app_names.append( this_name ) # for pretty display
            
            app_paths[f"{this_name}"] = f"/apps/{entry}"

        elif entry.endswith(".mpy"):
            this_name = entry[:-4]
            if this_name not in app_names:
                app_names.append( this_name )
            app_paths[f"{this_name}"] = f"/apps/{entry}"
            
            
    for entry in sd_app_list:
        if entry.endswith(".py"): #repeat for sdcard
            this_name = entry[:-3]
            
            if this_name not in app_names:
                app_names.append( this_name )
            
            app_paths[f"{this_name}"] = f"/sd/apps/{entry}"
            
        elif entry.endswith(".mpy"):
            this_name = entry[:-4]
            if this_name not in app_names:
                app_names.append( this_name )
            app_paths[f"{this_name}"] = f"/sd/apps/{entry}"
            
    #sort alphabetically without uppercase/lowercase discrimination:
    app_names.sort(key=lambda element: element.lower())
    
    #add an appname to refresh the app list
    app_names.append("Reload Apps")
    #add an appname to control the beeps
    app_names.append("UI Sound")
    #add an appname to open settings app
    app_names.append("Settings")
    app_paths["Settings"] = "/launcher/settings.py"
    
    gc.collect()
    return app_names, app_paths, sd




#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Function Definitions: ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

def launch_app(app_path):
    #print(f'launching {app_path}')
    rtc = machine.RTC()
    rtc.memory(app_path)
    print(f"Launching '{app_path}...'")
    # reset clock speed to default. 
    machine.freq(160_000_000)
    time.sleep_ms(10)
    machine.reset()
    



def center_text_x(text, char_width = 16):
    """
        Calculate the x coordinate to draw a text string, to make it horizontally centered. (plus the text width)
    """
    str_width = len(text) * char_width
    # display is 240 px wide
    start_coord = 120 - (str_width // 2)
    
    return start_coord, str_width


def easeOutCubic(x):
    return 1 - ((1 - x) ** 3)

def ease_in_out_cubic(x):
    if x < 0.5:
        return 4 * x * x * x
    else:
        return 1 - ((-2 * x + 2) ** 3) / 2

def ease_in_out_quart(x):
    if x < 0.5:
        return 8 * x * x * x * x
    else:
        return 1 - ((-2 * x + 2) ** 4) / 2

def time_24_to_12(hour_24,minute):
    ampm = 'am'
    if hour_24 >= 12:
        ampm = 'pm'
        
    hour_12 = hour_24 % 12
    if hour_12 == 0:
        hour_12 = 12
        
    time_string = f"{hour_12}:{'{:02d}'.format(minute)}"
    return time_string, ampm


def read_battery_level(adc):
    """
    read approx battery level on the adc and return as int range 0 (low) to 3 (high)
    """
    raw_value = adc.read_uv() # vbat has a voltage divider of 1/2
    
    # more real-world data is needed to dial in battery level.
    # the original values were low, so they will be adjusted based on feedback.
    
    #originally 525000 (1.05v)
    if raw_value < 1575000: #3.15v
        return 0
    #originally 1050000 (2.1v)
    if raw_value < 1750000: #3.5v
        return 1
    #originally 1575000 (3.15v)
    if raw_value < 1925000: #3.85v
        return 2
    # 2100000 (4.2v)
    return 3 # 4.2v or higher



# ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ GRAPHICS ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
def scroll_text():
    """Handle scrolling animation for app text (buf_idx = 2)"""
    global tft, scroll_factor, prev_text_scroll_position, text_scroll_position, text_drawing
    global app_names, app_selector_index, prev_selector_index, config, appname_y
    
    if scroll_factor < 0: # handle negative numbers
        text_ease_factor = -ease_in_out_quart( abs(scroll_factor * scroll_factor))
    else:
        text_ease_factor = ease_in_out_quart(scroll_factor * scroll_factor)
        
    # scroll text out of view using scroll method
    text_scroll_position = int(text_ease_factor * 240)
    tft.scroll(text_scroll_position - prev_text_scroll_position, 0, buf_idx=2)
    
    if abs(text_scroll_position) < 120:
        #blackout the old text
        if text_scroll_position == 0: # full blackout
            tft.fill(config['bg_color'], buf_idx = 2)
            
        else: # partial blackout
            blackout_width = (min(len(app_names[prev_selector_index]), 15)) * 16
            tft.rect((120 - (blackout_width // 2)) + text_scroll_position, 80, blackout_width, 32, config['bg_color'], fill=True, buf_idx=2)
            #also blackout right or left (depending on scroll direction) to prevent streaks
            scroll_size = abs(text_scroll_position - prev_text_scroll_position)
            if text_scroll_position > 0:
                tft.rect(240 - (scroll_size), 80, scroll_size, 32, config['bg_color'], fill=True, buf_idx=2)
            else:
                tft.rect(0, 80, scroll_size, 32, config['bg_color'], fill=True, buf_idx=2)
            
        #crop text for display
        current_app_text = app_names[app_selector_index]
        if len(current_app_text) > 15:
            current_app_text = current_app_text[:12] + "..."

        #draw new text
        tft.bitmap_text(font, current_app_text, center_text_x(current_app_text)[0] + text_scroll_position, 80, config['ui_color'], buf_idx=2)
    tft.show(buf_idx=2)
    
    
def scroll_icon():
    """Handle scrolling animation for app icon (buf_idx = 1)"""
    global tft, scroll_factor, prev_icon_scroll_position, icon_scroll_position, icon_drawing
    global app_names, app_selector_index, config, app_paths
    
    if scroll_factor < 0: # handle negative numbers
        icon_ease_factor = -ease_in_out_cubic( abs(scroll_factor * scroll_factor))
    else:
        icon_ease_factor = ease_in_out_cubic(scroll_factor * scroll_factor)
    
    # scroll text out of view using scroll method
    icon_scroll_position = int(icon_ease_factor * 240)
    tft.scroll(icon_scroll_position - prev_icon_scroll_position, 0, buf_idx=1)
    
    if 40 < abs(icon_scroll_position) < 80 or icon_scroll_position == 0:
        # redraw icons
        #blackout old icon
        tft.fill(config['bg_color'], buf_idx=1)
        
        current_app_text = app_names[app_selector_index]
        #special menu options for settings
        if current_app_text == "UI Sound":
            if config['ui_sound']:
                tft.bitmap_text(font, "On", center_text_x("On")[0] + icon_scroll_position, 36, config['ui_color'], buf_idx=1)
            else:
                tft.bitmap_text(font, "Off", center_text_x("Off")[0] + icon_scroll_position, 36, config.palette[3], buf_idx=1)
                
        elif current_app_text == "Reload Apps":
            tft.bitmap_icons(icons, icons.RELOAD, config['ui_color'],104 + icon_scroll_position, 36, buf_idx=1)
            
        elif current_app_text == "Settings":
            tft.bitmap_icons(icons, icons.GEAR, config['ui_color'],104 + icon_scroll_position, 36, buf_idx=1)
            
        elif app_paths[app_names[app_selector_index]][:3] == "/sd":
            tft.bitmap_icons(icons, icons.SDCARD, config['ui_color'],104 + icon_scroll_position, 36, buf_idx=1)
        else:
            tft.bitmap_icons(icons, icons.FLASH, config['ui_color'],104 + icon_scroll_position, 36, buf_idx=1)
    tft.show(buf_idx=1)

def draw_status_bar():
    """Handle redrawing the status bar (buf_idx = 0)"""
    global tft, buf_0_modified, config, batt
    
    tft.fill(config['bg_color'], buf_idx=0)
    tft.fill_rect(0,0,240, 16, config.palette[2], buf_idx=0)
    tft.hline(0,17,240, config.palette[0], buf_idx=0) # shadow
    
    #clock
    _,_,_, hour_24, minute, _,_,_ = time.localtime()
    formatted_time, ampm = time_24_to_12(hour_24, minute)
    tft.text(formatted_time, 11,5,config.palette[0], buf_idx=0) # shadow
    tft.text(formatted_time, 10,4,config['ui_color'], buf_idx=0)
    tft.text(ampm, 11 + (len(formatted_time) * 8),5,config.palette[0], buf_idx=0) # shadow
    tft.text(ampm, 10 + (len(formatted_time) * 8),4,config.palette[4], buf_idx=0)
    
    #battery
    battlevel = read_battery_level(batt)
    tft.bitmap_icons(battery, battery.FULL, config.extended_colors[0],209, 4, buf_idx=0) # shadow
    if battlevel == 3:
        tft.bitmap_icons(battery, battery.FULL, config.extended_colors[1],208, 3, buf_idx=0)
    elif battlevel == 2:
        tft.bitmap_icons(battery, battery.HIGH, config['ui_color'],208, 3, buf_idx=0)
    elif battlevel == 1:
        tft.bitmap_icons(battery, battery.LOW, config['ui_color'],208, 3, buf_idx=0)
    else:
        tft.bitmap_icons(battery, battery.EMPTY, config.extended_colors[0],208, 3, buf_idx=0)
    tft.show(buf_idx=0)
    buf_0_modified = True
    
def draw_scroll_bar():
    """Handle redrawing the scroll bar (buf_idx = 3)"""
    global tft, buf_3_modified, config, app_selector_index, app_names
    
    tft.fill(config['bg_color'], buf_idx=3)
    
    exact_scrollbar_width = 232 / len(app_names)
    scrollbar_width = int(exact_scrollbar_width)
    tft.rect(int(exact_scrollbar_width * app_selector_index) + 4,131,
             scrollbar_width,4,config.palette[4], fill=True, buf_idx=3)
    tft.rect(int(exact_scrollbar_width * app_selector_index) + 4,131,
             scrollbar_width,4,config.palette[2], fill=False, buf_idx=3)
    tft.show(buf_idx=3)

#--------------------------------------------------------------------------------------------------
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Main Loop: ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
#--------------------------------------------------------------------------------------------------

def main_loop():
    global scroll_factor, prev_text_scroll_position, text_scroll_position, text_drawing, prev_icon_scroll_position
    global icon_scroll_position, icon_drawing, buf_0_modified, buf_1_modified, buf_2_modified, buf_3_modified
    global app_selector_index, prev_selector_index, app_names, app_paths, clock_minute_drawn, batt
    
    
    #bump up our clock speed so the UI feels smoother (240mhz is the max officially supported, but the default is 160mhz)
    machine.freq(240_000_000)
    
        
    # sync our RTC on boot, if set in settings
    syncing_clock = config['sync_clock']
    sync_ntp_attemps = 0
    connect_wifi_attemps = 0
    rtc = machine.RTC()
    

    if config['wifi_ssid'] == '':
        syncing_clock = False # no point in wasting resources if wifi hasn't been setup
    elif rtc.datetime()[0] != 2000: #clock wasn't reset, assume that time has already been set
        syncing_clock = False
        
    if syncing_clock and nic != None: #enable wifi if we are syncing the clock
        if not nic.active(): # turn on wifi if it isn't already
            nic.active(True)
        if not nic.isconnected(): # try connecting
            try:
                nic.connect(config['wifi_ssid'], config['wifi_pass'])
            except OSError as e:
                print("wifi_sync_rtc had this error when connecting:",e)
    
    #before anything else, we should scan for apps
    sd = None #dummy var for when we cant mount SDCard
    app_names, app_paths, sd = scan_apps(sd)
    
    app_selector_index = 0
    prev_selector_index = 0
    
    #init the keyboard
    kb = keyboard.KeyBoard()
    
    #init the ADC for the battery
    batt = machine.ADC(10)
    batt.atten(machine.ADC.ATTN_11DB)

    
    #nonscroll_elements_displayed = False
    
    force_redraw_display = True
    
    #this is used as a flag to tell a future loop to redraw the frame mid-scroll animation
    delayed_redraw = False
    
    #starupp sound
    if config['ui_sound']:
        beep.play(('C3',
                   ('F3'),
                   ('A3'),
                   ('F3','A3','C3'),
                   ('F3','A3','C3')),130,config['volume'])
        
        
    # init diplsay
    # icons
    tft.fill(config['bg_color'], buf_idx=1)
    tft.show(buf_idx=1)
    # text
    tft.fill(config['bg_color'], buf_idx=2)
    tft.show(buf_idx=2)
    # scroll bar
    tft.fill(config['bg_color'], buf_idx=3)
    tft.show(buf_idx=3)
    
    loop_timer = 0
    
    while True:
        # ----------------------- check for key presses on the keyboard. Only if they weren't already pressed. --------------------------
        new_keys = kb.get_new_keys()
        if new_keys:
            
            # ~~~~~~ check if the arrow keys are newly pressed ~~~~~
            if "/" in new_keys: # right arrow
                app_selector_index += 1
                
                #animation:
                scroll_factor = 1.0
                text_drawing = True
                icon_drawing = True
                prev_text_scroll_position = 240
                text_scroll_position = 240
                prev_icon_scroll_position = 240
                icon_scroll_position = 240
                
                if config['ui_sound']:
                    beep.play((("C5","D4"),"A4"), 80, config['volume'])

                
            elif "," in new_keys: # left arrow
                app_selector_index -= 1
                
                #animation:
                
                #scroll_direction = -1
                scroll_factor = -1.0
                text_drawing = True
                icon_drawing = True
                prev_text_scroll_position = -240
                text_scroll_position = -240
                prev_icon_scroll_position = -240
                icon_scroll_position = -240
                
                if config['ui_sound']:
                    beep.play((("B3","C5"),"A4"), 80, config['volume'])
                
            
        
            # ~~~~~~~~~~ check if GO or ENTER are pressed ~~~~~~~~~~
            if "GO" in new_keys or "ENT" in new_keys:
                
                # special "settings" app options will have their own behaviour, otherwise launch the app
                if app_names[app_selector_index] == "UI Sound":
                    
                    if config['ui_sound'] == 0: # currently muted, then unmute
                        config['ui_sound'] = True
                        force_redraw_display = True
                        beep.play(("C4","G4","G4"), 100, config['volume'])
                    else: # currently unmuted, then mute
                        config['ui_sound'] = False
                        force_redraw_display = True
                
                elif app_names[app_selector_index] == "Reload Apps":
                    app_names, app_paths, sd = scan_apps(sd)
                    app_selector_index = 0
                    current_vscsad = 42 # forces scroll animation triggers
                    if config['ui_sound']:
                        beep.play(('F3','A3','C3'),100,config['volume'])
                        
                else: # ~~~~~~~~~~~~~~~~~~~ LAUNCH THE APP! ~~~~~~~~~~~~~~~~~~~~
                    
                    #save config if it has been changed:
                    config.save()
                    
                    # shut off the display
                    tft.fill(0)
                    tft.sleep_mode(True)
                    machine.Pin(38, machine.Pin.OUT).value(0) #backlight off
                    spi.deinit()
                    
                    if sd != None:
                        try:
                            sd.deinit()
                        except:
                            print("Tried to deinit SDCard, but failed.")
                            
                    if config['ui_sound']:
                        beep.play(('C4','B4','C5','C5'),100,config['volume'])
                        
                    launch_app(app_paths[app_names[app_selector_index]])

            else: # keyboard shortcuts!
                for key in new_keys:
                    # jump to letter:
                    if len(key) == 1: # filter special keys and repeated presses
                        if key in 'abcdefghijklmnopqrstuvwxyz1234567890':
                            #search for that letter in the app list
                            for idx, name in enumerate(app_names):
                                if name.lower().startswith(key):
                                    #animation:
                                    if app_selector_index > idx:
                                        #scroll_direction = -1
                                        scroll_factor = -1.0
                                        text_drawing = True
                                        icon_drawing = True
                                        prev_text_scroll_position = -240
                                        text_scroll_position = -240
                                        prev_icon_scroll_position = -240
                                        icon_scroll_position = -240
                                        
                                    elif app_selector_index < idx:
                                        scroll_factor = 1.0
                                        text_drawing = True
                                        icon_drawing = True
                                        prev_text_scroll_position = 240
                                        text_scroll_position = 240
                                        prev_icon_scroll_position = 240
                                        icon_scroll_position = 240
                                        #scroll_direction = 1
                                    #current_vscsad = target_vscsad
                                    # go there!
                                    app_selector_index = idx
                                    if config['ui_sound']:
                                        beep.play(("G3"), 100, config['volume'])
                                    found_key = True
                                    break
        
        
        #wrap around our selector index, in case we go over or under the target amount
        app_selector_index = app_selector_index % len(app_names)
    
    
        time.sleep_ms(1)
        
        
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ Main Graphics: ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        
        
        # handle scroll_factor
        if scroll_factor != 0:
            if scroll_factor > 0:
                scroll_factor -= min(0.1, abs(scroll_factor))
            else:
                scroll_factor += min(0.1, abs(scroll_factor))
        
        if text_drawing:
            scroll_text()
            if text_scroll_position == 0:
                text_drawing = False
            
        if icon_drawing:
            scroll_icon()
            if icon_scroll_position == 0:
                icon_drawing = False
                
        if time.localtime()[4] != clock_minute_drawn:
            clock_minute_drawn = time.localtime()[4]
            draw_status_bar()
            
        if app_selector_index != prev_selector_index:
            draw_scroll_bar()

        # reset vars for next loop
        force_redraw_display = False
        prev_selector_index = app_selector_index
        prev_text_scroll_position = text_scroll_position
        prev_icon_scroll_position = icon_scroll_position
        loop_timer = (loop_timer + 1) % 10
        
        #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~ WIFI and RTC: ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        
        if syncing_clock and nic != None:
            if nic.isconnected():
                try:
                    ntptime.settime()
                except OSError:
                    sync_ntp_attemps += 1
                    
                if rtc.datetime()[0] != 2000:
                    nic.disconnect()
                    nic.active(False) #shut off wifi
                    syncing_clock = False
                    #apply our timezone offset
                    time_list = list(rtc.datetime())
                    time_list[4] = time_list[4] + config['timezone']
                    rtc.datetime(tuple(time_list))
                    print(f'RTC successfully synced to {rtc.datetime()} with {sync_ntp_attemps} attemps.')
                    
                elif sync_ntp_attemps >= max_ntp_attemps:
                    nic.disconnect()
                    nic.active(False) #shut off wifi
                    syncing_clock = False
                    print(f"Syncing RTC aborted after {sync_ntp_attemps} attemps")
                
            elif connect_wifi_attemps >= max_wifi_attemps:
                nic.disconnect()
                nic.active(False) #shut off wifi
                syncing_clock = False
                print(f"Connecting to wifi aborted after {connect_wifi_attemps} loops")
            else:
                connect_wifi_attemps += 1
        
# run the main loop!
main_loop()




