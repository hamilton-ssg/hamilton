#!/usr/bin/env python3
from pathlib import Path
from bs4 import BeautifulSoup as bs
from commonmark import commonmark
from dirsync import sync
import os, shutil, subprocess, re, sys, argparse, fnmatch, time, toml

DEFAULT_TEMPLATE = bs('<!DOCTYPE html><html><head><meta charset="utf-8"><title>[#title#]</title><meta property="og:type" content="website"><meta property="og:image" content=""><meta name="og:site_name" content="hamilton"><meta name="og:title" content="[#title#]"><meta name="og:description" content="[#description#]"><meta name="theme-color" content="#333333"></head><body><header><h2>[#title#]</h2></header><main>[#content#]</main><footer><hr><p>Generated with hamilton</p></footer></body></html>', "html.parser").prettify()

HEADER = """
    __                    _ ____            
   / /_  ____ _____ ___  (_) / /_____  ____ 
  / __ \/ __ `/ __ `__ \/ / / __/ __ \/ __ \ 
 / / / / /_/ / / / / / / / / /_/ /_/ / / / / 
/_/ /_/\__,_/_/ /_/ /_/_/_/\__/\____/_/ /_/ 
                                            
"""

SKIP_IN_FOLDER = [
    "Thumbs.db", # common meta file in windows
    ".DS_Store" # common meta file in Mac OS X
] # add to this list if you need to prevent hamilton from processing a file (fnmatch syntax)

# maximum amount of conditionals to process in one file
# if processing continues past this point, an exception will be raised (probably means broken conditional; they're still hacky despite my best efforts)
MAX_CONDITIONALS = 250

ATTRIBUTES = re.compile(r'(?<!\\)\[#([^#]+)#\]')
CONDITIONALS = re.compile(r'(?<!\\)\[([^=]*)=([^\]]*?)\](.*?)\[\/\1.*\]',re.DOTALL)
BLOCKTAGS = re.compile(r"(?<!\\){#([^|]+)((?:\|[A-Za-z0-9]+=[^|]+)*)#}")
ESCAPED_ATTRIBUTES = re.compile(r'\\\[#([^#]+)#\]')
ESCAPED_CONDITIONALS = re.compile(r'\\\[([^=]*)=([^\]]*?)\](.*?)\\\[\/\1.*\]',re.DOTALL)
ESCAPED_BLOCKTAGS = re.compile(r"\\{#([^|]+)((?:\|[A-Za-z0-9]+=[^|]+)*)#}")

class ansicolors:
    BLACK="\033[30m"
    RED="\033[31m"
    GREEN="\033[32m"
    YELLOW="\033[33m"
    BLUE="\033[34m"
    MAGENTA="\033[35m"
    CYAN="\033[36m"
    WHITE="\033[37m"
    RESET="\033[0m"
    BOLD="\033[1m"

    @classmethod
    def disable(self):
        if not hasattr(self,"_backup"):
            self._backup = {}
            self._backup.update(self.__dict__)
        self.BLACK=""
        self.RED=""
        self.GREEN=""
        self.YELLOW=""
        self.BLUE=""
        self.MAGENTA=""
        self.CYAN=""
        self.WHITE=""
        self.RESET=""
        self.BOLD=""

    @classmethod
    def enable(self):
        if not hasattr(self,"_backup"): return
        self.__dict__.update(self._backup)

# Plugin support
REGPREPROCESSORS = {}
REGPOSTPROCESSORS = {}
REGBLOCKTAGS = {}

def register(registry, name, func):
    registry[name]=func

def preprocessor(name):
    def __wrapper(func):
        register(REGPREPROCESSORS,name,func)
        return func
    return __wrapper

def blocktag(name):
    def __wrapper(func):
        register(REGBLOCKTAGS,name,func)
        return func
    return __wrapper

def postprocessor(name):
    def __wrapper(func):
        register(REGPOSTPROCESSORS,name,func)
        return func
    return __wrapper

def evalplugin(src):
    global preprocessor, blocktag, postprocessor
    exec(src,globals(),locals())

def initplugins():
    if not Path("plugins/").is_dir(): return
    for plugin in os.listdir("plugins"):
        if not plugin.endswith(".py"): continue
        with open("plugins/"+plugin) as f:
            evalplugin(f.read())
# End plugin support

def dirname(path):
    # Replacement for os.path.dirname() which is broken on some versions of Python (3.5.2 and maybe others)
    return '/'.join(str(path).split('/')[:-1])

def sanity_check_environment():
    input_dir = "pages/"
    # Use default template
    template = Path('templates/default.html')
    # Check if exists
    if template.is_file():
        # It does
        print(ansicolors.GREEN + 'templates/default.html exists' + ansicolors.RESET)
    else:
        # It doesn't
        print(ansicolors.YELLOW + 'templates/default.html does not exist yet' + ansicolors.RESET)

    indir = Path("pages/")
    # Check if indir exists
    if indir.is_dir():
        # It does
        print(ansicolors.GREEN + 'pages folder exists' + ansicolors.RESET)
    else:
        # It doesn't
        # Does the `in/` folder exist?
        if Path('in/').is_dir():
            print(ansicolors.YELLOW + 'legacy in folder detected, using instead of pages' + ansicolors.RESET)
            # set the input_dir variable for on return
            input_dir = 'in/'
        else:
            print(ansicolors.YELLOW + 'pages folder does not exist yet' + ansicolors.RESET)

    includes = Path("includes/")
    # Check if includes folder exists
    if includes.is_dir():
        # It does
        print(ansicolors.GREEN + 'includes folder exists' + ansicolors.RESET)
    else:
        # It doesn't
        print(ansicolors.YELLOW + 'includes folder does not exist yet' + ansicolors.RESET)

    print()

    # Create template file if it doesn't exist
    if not template.is_file():
        # It doesn't
        # Make templates directory
        if not Path('templates/').is_dir():
            os.mkdir('templates')
        # Check if there is an old template.html file and migrate it
        oldtemplate = Path('template.html')
        if oldtemplate.is_file():
            print(ansicolors.GREEN + 'Legacy template.html exists, migrating' + ansicolors.RESET)
            # Copy template.html to templates/default.html
            shutil.copyfile('template.html', 'templates/default.html')
        else:
            print(ansicolors.YELLOW + 'Creating templates/default.html' + ansicolors.RESET)
            with open(str(template), 'w') as f:
                # Write default template to file
                f.write(DEFAULT_TEMPLATE)
                f.close()

    # Create in folder if it doesn't exist
    if not indir.is_dir() and input_dir=='pages/':
        # It doesn't
        print(ansicolors.YELLOW + 'Creating pages folder' + ansicolors.RESET)
        # Make it
        os.mkdir("pages")

    # Create includes folder if it doesn't exist
    if not includes.is_dir():
        # It doesn't
        print(ansicolors.YELLOW + 'Creating includes folder' + ansicolors.RESET)
        # Make it
        os.mkdir("includes")
    return input_dir

def walk_in_folder(input_dir):
    files = []
    # Go through each file in input folder
    for dirName, subdirList, fileList in os.walk(input_dir):
        for path in os.listdir(dirName):
            # Check if file has extension
            if '.' in path:
                # Check if it isn't common meta files used by OS X and Windows (or anything else we're configured to ignore)
                if not any([fnmatch.fnmatch(path,pattern) for pattern in SKIP_IN_FOLDER]):
                    # Add the file to the list
                    files.append((dirName + "/" + path).replace('\\', '/').replace('//', '/').replace(input_dir, '', 1))
    return files

def replace_attributes(attribs):
    def __replace(m):
        attrib = m.group(1)
        if attrib not in attribs: return m.group(0) # full match, maintains backwards compat of not replacing undefined attributes
        return attribs[attrib]
    return __replace

def process(path, input_dir, _attribs, template_cache={}):
    # Check if it exists
    if os.path.isfile(input_dir + path):
        # If it's markdown let user know it'll be translated into html
        if path.endswith('.md'):
            print(ansicolors.BOLD + 'Path: ' + ansicolors.RESET + ansicolors.GREEN + path + ansicolors.RESET + ' ==> ' + ansicolors.GREEN + path[:-2] + 'html' + ansicolors.RESET)
        else:
            print(ansicolors.BOLD + 'Path: ' + ansicolors.RESET + ansicolors.GREEN + path + ansicolors.RESET)

        # Open, read file
        f = open(input_dir + path, 'r', encoding="utf8")
        filearray = f.readlines()
        contentarray = filearray
        # Filter out attributes from contentarray
        if len(contentarray) > 0:
            while contentarray[0].startswith('<!-- '):
                if len(contentarray) > 0:
                    contentarray = contentarray[1:]
                    if len(contentarray) < 1:
                        break
        # Set the content to everything in the contentarray
        content = ''.join(contentarray)
        # Close the file
        f.close()

        # Check if a markdown file
        if path.endswith('.md'):
            # If it is, run it through commonmark to translate it into html
            content = commonmark(content)

        # Default attributes
        attribs = {'title': '', 'description': '', 'template': 'default', 'modified': time.strftime('%m/%d/%Y', time.gmtime(os.path.getmtime(input_dir+path)))}
        attribs.update(_attribs)

        # Handle legacy attributes (also known as a mess)

        # These would work like:
        #    1st line: title
        #    2nd line: description
        #    3rd line: template

        # Check if it is a legacy title
        if filearray[0].startswith('<!-- ') and not filearray[0].startswith('<!-- attrib'):
            # Set title variable
            attribs['title'] = filearray[0].replace('<!--', '').replace('-->', '').strip()
            print(ansicolors.BOLD + 'Legacy Title: ' + ansicolors.RESET + ansicolors.GREEN + attribs['title'] + ansicolors.RESET)
            filearray = filearray[1:]

        # Check if it is a legacy description
        if filearray[0].startswith('<!-- ') and not filearray[0].startswith('<!-- attrib'):
            # Set description variable
            attribs['description'] = filearray[0].replace('<!--', '').replace('-->', '').strip()
            print(ansicolors.BOLD + 'Legacy Description: ' + ansicolors.RESET + ansicolors.GREEN + attribs['description'] + ansicolors.RESET)
            filearray = filearray[1:]

        # Check if it is a legacy template
        if filearray[0].startswith('<!-- ') and not filearray[0].startswith('<!-- attrib'):
            # Set template variable
            attribs['template'] = filearray[0].replace('<!--', '').replace('-->', '').strip()
            print(ansicolors.BOLD + 'Legacy Template: ' + ansicolors.RESET + ansicolors.GREEN + attribs['template'] + ansicolors.RESET)
            filearray = filearray[1:]

        # Handle new attributes

        # Open, read file
        f = open(input_dir + path, 'r', encoding="utf8")
        filearray = f.readlines()
        f.close()

        # For each line
        while len(filearray) > 0:
            # Check if it is an attribute
            if filearray[0].startswith('<!-- attrib '):
                # Get the attribute being set
                attrib = filearray[0].replace('<!-- attrib ', '').replace('-->', '').strip().split(': ')[0]
                # Get the value it's being set to
                value = filearray[0].replace('<!-- attrib ', '').replace('-->', '').strip().split(': ')[1]
                print(ansicolors.BOLD + 'Attribute ' + attrib + ': ' + ansicolors.RESET + ansicolors.GREEN + value + ansicolors.RESET)
                # Add to attributes
                attribs[attrib] = value
            filearray = filearray[1:]

        # Unpublish - allows preventing a file from rendering
        if "unpublish" in attribs and attribs["unpublish"][0].lower() not in ('n', 'f'):
            print(ansicolors.RED + "Skipping due to unpublish setting" + ansicolors.RESET)
            return

        template = ''

        # Check if template is cached
        if attribs['template'] in template_cache.keys():
            template = template_cache[attribs['template']]
        else:
            # If not then load it;
            # Get the template's path
            print('Caching template', attribs['template'])
            template = 'templates/' + attribs['template'] + '.html'

            # If it doesn't exist, then create it from the default
            if not Path(template).is_file():
                print(ansicolors.YELLOW + 'Template', template, 'does not exist. Using default template instead.' + ansicolors.RESET)
                template = 'templates/default.html'

            # Read template file
            f = open(template, 'r', encoding="utf8")
            template = f.read()
            f.close()
            # Cache
            template_cache[attribs['template']] = template

        # Create subdirectories
        os.makedirs(dirname('out/' + path), exist_ok=True)

        # If there aren't any subdirectories between root and the file, use ./ as the slash so it doesn't refer to the root of the server for file:// compatibility
        if path.count('/') == 0:
            slash = './'
        else:
            slash = '/'

        # Set path and root attributes
        attribs['path'] = path
        attribs['root'] = (('../' * path.count('/')) + slash).replace('//', '/')

        # cleanpath is just path with the index.html/index.md stripped
        if path.endswith("index.html") or path.endswith("index.md"):
            attribs['cleanpath'] = dirname(path)
        else:
                attribs['cleanpath'] = path
        # replace .md with .html here
        if attribs['cleanpath'].endswith('.md'): attribs['cleanpath'] = attribs['cleanpath'].rsplit('.',1)[0]+".html"

        # Attribute pass 1
        template = ATTRIBUTES.sub(replace_attributes(attribs),template)

        # Preprocessors run on the content alone, before substitution of variables
        for preprocessor in sorted(REGPREPROCESSORS.keys()):
            content = REGPREPROCESSORS[preprocessor](content,attribs)

        template = template.replace("[#content#]",content)

        # Now let's handle conditional text
        # Conditional text is an experimental feature.
        # I kind of fixed it up a little. Conditionals can now be multiline, and nested.
        # Example:

        # [path!=pages/link.html]<a href="[#root#]pages/link.html">[/path!=]
        #    Linking
        # [path!=pages/link.html]</a>[/path!=]

        # This works with any attribute.


        conditionals_count = 0
        while (m:=CONDITIONALS.search(template)):
            assert conditionals_count<MAX_CONDITIONALS, "Too many conditionals parsed! Try rewriting your conditional statements."
            conditionals_count += 1
            atteql, value, text = m.groups()
            # Add equal sign to =
            # atteql is the combination of the attribute and the equal sign
            # If atteql was !, for (if not) then it would be !=, if it was nothing, it'd be =. absolute genius!!!
            atteql += '='
            # Get the attribute
            attribute = atteql.replace('!=', '').replace('=', '')
            # Get the equal sign
            equals = atteql.replace(attribute, '')

            # Whether to display
            trigger = False

            # For each attribute
            for key, val in attribs.items():
                # If it's the one we're looking for
                if key == attribute:
                    # If the provided value is empty (not bool(value)), just consider it triggered
                    if not value:
                        trigger = True
                    else:
                        # If the value is equal
                        if val == value:
                            # Trigger
                            trigger = True

            # Check if we're going to display if it is NOT equal
            if equals == '!=':
                # Reverse the trigger
                trigger = not trigger

            # If triggered
            if trigger:
                # Set it to the text
                template = template.replace('[' + atteql + value + ']' + text + '[/' + atteql + ']', text)
            else:
                # Make it blank
                template = template.replace('[' + atteql + value + ']' + text + '[/' + atteql + ']', '')

        # now for blocktags
        for name, argslist in BLOCKTAGS.findall(template):
            # raw blocktag, for substitution later
            raw = "{#"+name+argslist+"#}"
            # fancy way of parsing arguments
            argslist = dict([tuple(arg.split("=",1)) for arg in argslist[1:].split("|")]) if argslist else {}
            # make sure we have a blocktag for this case
            try:
                assert name in REGBLOCKTAGS, f"Undefined blocktag {name!r}, skipping..."
                result = REGBLOCKTAGS[name](attribs,**argslist)
                res_type = type(result)
                assert res_type==str, f"Expected string result from blocktag {name!r}, received {res_type!r} instead..."
            except AssertionError as e:
                print(f"ERROR: {e.args[0]}")
                continue # don't crash on undefined/errant blocktags
            # if it passes the checks, run it
            template = template.replace(raw,result)

        # Attribute pass 2
        template = ATTRIBUTES.sub(replace_attributes(attribs),template)

        # If this is a markdown file
        if path.endswith('.md'):
            # Trim the md from it and make the output extension html
            path = path[:-2] + 'html'

        # replace escaped attributes/conditionals/blocktags with their literal forms
        template = ESCAPED_ATTRIBUTES.sub(lambda m: m.group(0)[1:],template)
        template = ESCAPED_CONDITIONALS.sub(lambda m: m.group(0)[1:][::-1].replace("/[\\","/[")[::-1],template)
        template = ESCAPED_BLOCKTAGS.sub(lambda m: m.group(0)[1:],template)

        # Postprocessors run on the entire output
        for postprocessor in sorted(REGPOSTPROCESSORS.keys()):
            template = REGPOSTPROCESSORS[postprocessor](template,attribs)

        # Open file and write our contents
        f = open('out/' + path, 'w', encoding="utf8")
        f.write(template)
        f.close()

        # We are done!
        print(ansicolors.BOLD + ansicolors.GREEN + 'Wrote to out/' + path + ansicolors.RESET)
        print()

def main():
    # Default parameters
    # Set these and they will always be active whether parameters are passed or not
    boring = False
    silent = False
    directory = False # Set to path

    config = {}
    if Path('config.toml').is_file():
        with open('config.toml') as f:
            config = toml.load(f)
        for key in config.get("build_settings",{}):
            if key=="boring": boring=config["build_settings"][key]
            if key=="silent": silent=config["build_settings"][key]
            if key=="directory": directory=config["build_settings"][key]

    # Enable colors
    subprocess.call('', shell=True)

    # Define arguments, help
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument('-b', '--boring', action='store_true', help='disables colors/formatting')
    parser.add_argument('-s', '--silent', action='store_true', help='runs silently, skipping user input')
    parser.add_argument('-d', '--dir', action='store', help='run hamilton at a specific location')
    # Parse
    args = parser.parse_args()

    if args.boring:
        boring = True
    if args.silent:
        silent = True
    if args.dir:
        directory = args.dir

    # Disable colors with boring argument
    if boring:
        ansicolors.disable()
    else:
        ansicolors.enable()

    # Disable printing to console with silent argument
    if silent:
        sys.stdout = open(os.devnull, 'w')

    # Change working directory if called for
    if directory:
        try:
            os.chdir(directory)
        except FileNotFoundError:
            os.makedirs(directory)
            os.chdir(directory)
        if Path('config.toml').is_file():
            with open('config.toml') as f:
                config2 = toml.load(f)
            for key in config2.get("build_settings",{}):
                if key=="boring" and not args.boring: boring=config["build_settings"][key]
                if key=="silent" and not args.silent: silent=config["build_settings"][key]
                # ignore directory directive in cascading TOML file
            if "attributes" not in config2: config2["attributes"] = {}
            # prefer the original config's attributes
            config2["attributes"].update(config.get("attributes",{}))
            config["attributes"]=config2["attributes"]

    # Even worse blatant self-advertising
    print(ansicolors.BOLD + HEADER + ansicolors.RESET)
    print()
    print(ansicolors.BOLD + 'Path: ' + ansicolors.RESET + os.getcwd())

    # execute sanity check on environment (is there the folders we need? try to make them?)
    input_dir = sanity_check_environment()

    # init plugins
    print(ansicolors.MAGENTA + 'Initializing plugins' + ansicolors.RESET)
    initplugins()

    # Gather files
    print(ansicolors.MAGENTA + ansicolors.BOLD + 'Gathering file paths' + ansicolors.RESET)
    files = walk_in_folder(input_dir)
    # Print it out
    print(files)

    outdir = Path("out/")
    # Create output directory if it doesn't exist
    if not outdir.is_dir():
        # It doesn't
        print(ansicolors.YELLOW + 'Creating out folder' + ansicolors.RESET)
        # Make it
        os.mkdir("out")

    # Sync includes folder to out folder first of all
    print(ansicolors.MAGENTA + ansicolors.BOLD + 'Syncing includes to out folder' + ansicolors.RESET)
    sync('includes/', 'out/', 'sync', purge=True)

    # Process input files
    print(ansicolors.MAGENTA + ansicolors.BOLD + 'Going through input files' + ansicolors.RESET)
    print()

    # Run the process for each file
    for path in files: process(path, input_dir, config.get("attributes",{}))

    # All files processed
    print(ansicolors.BOLD + ansicolors.GREEN + 'Finished.' + ansicolors.RESET)
    # Terminate to avoid repeats
    sys.exit()

# If not run through package script "hamilton" (in that case the script would already have run and terminated itself), but from the file directly run
main()
